"""
Delete every order and reset the balances that came from them.

For clearing test data before a real launch. It does NOT touch user accounts,
passwords, saved carts, or the product catalog.

Balances are reset by default. Deleting orders without doing that would leave
people owing money for orders that no longer exist, since balance_owed is
accumulated as orders are placed. Pass --keep-balances if you want the amounts
preserved anyway.

Every run writes a CSV backup of the orders first, because this is otherwise
irreversible.

Usage:
    python wipe_orders.py                  # show what would go, then ask
    python wipe_orders.py --yes            # no prompt, for scripting
    python wipe_orders.py --dry-run        # report only
    python wipe_orders.py --keep-balances
"""

import argparse
import csv
import os
import sys
from datetime import datetime

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_ERROR = 3

CONFIRM_WORD = 'DELETE'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--yes', action='store_true',
                        help='skip the typed confirmation')
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would be deleted and stop')
    parser.add_argument('--keep-balances', action='store_true',
                        help='leave balance_owed alone instead of resetting it to 0')
    parser.add_argument('--no-backup', action='store_true',
                        help='skip the CSV backup (not recommended)')
    parser.add_argument('--local', action='store_true',
                        help='operate on the local SQLite file instead of DATABASE_URL')
    return parser.parse_args(argv)


def backup_orders(orders: list[dict]) -> str:
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = f'orders_backup_{stamp}.csv'
    fieldnames = list(orders[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(orders)
    return path


def main(argv=None) -> int:
    args = parse_args(argv)

    if not args.local and not os.environ.get('DATABASE_URL'):
        print('DATABASE_URL is not set.\n'
              'Set it to wipe the hosted database, or pass --local to wipe the\n'
              'local SQLite file instead.', file=sys.stderr)
        return EXIT_ERROR

    if args.local:
        os.environ.pop('DATABASE_URL', None)

    from db import get_all_orders, get_all_users, get_conn, _placeholder

    target = 'the LOCAL SQLite file' if args.local else 'the HOSTED database'

    orders = [dict(row) for row in get_all_orders()]
    users = [dict(row) for row in get_all_users()]
    owed = sum(float(u.get('balance_owed') or 0) for u in users)
    owing_users = [u for u in users if float(u.get('balance_owed') or 0) > 0]

    print(f'Target: {target}')
    print(f'  orders                {len(orders)}')
    print(f'  user accounts         {len(users)} (will NOT be deleted)')
    print(f'  total balance owed    ${owed:,.2f} across {len(owing_users)} user(s)')

    if orders:
        by_status: dict[str, int] = {}
        for order in orders:
            by_status[str(order.get('status'))] = by_status.get(str(order.get('status')), 0) + 1
        print('  by status             '
              + ', '.join(f'{k}: {v}' for k, v in sorted(by_status.items())))
        newest = max(str(o.get('timestamp') or '') for o in orders)
        oldest = min(str(o.get('timestamp') or '') for o in orders)
        print(f'  date range            {oldest}  ..  {newest}')

    if not orders and not owing_users:
        print('\nNothing to do.')
        return EXIT_OK

    print()
    print(f'This will delete all {len(orders)} order(s)'
          + ('' if args.keep_balances else f' and reset ${owed:,.2f} of balances to $0')
          + '.')
    print('Accounts, passwords, saved carts and the product catalog are untouched.')

    if args.dry_run:
        print('\nDry run, nothing changed.')
        return EXIT_OK

    backup_path = None
    if orders and not args.no_backup:
        backup_path = backup_orders(orders)
        print(f'\nBacked up {len(orders)} order(s) to {backup_path}')

    if not args.yes:
        print()
        reply = input(f'Type {CONFIRM_WORD} to confirm, anything else to abort: ')
        if reply.strip() != CONFIRM_WORD:
            print('Aborted. Nothing was changed.')
            return EXIT_ABORTED

    with get_conn() as conn:
        conn.execute('DELETE FROM order_items')
        conn.execute('DELETE FROM orders')
        if not args.keep_balances:
            conn.execute('UPDATE users SET balance_owed = 0')
        # Otherwise the next order re-triggers the batch email against a stale count.
        conn.execute(
            f'DELETE FROM app_state WHERE key = {_placeholder()}',
            ('last_ball_batch_notified_count',),
        )

    print(f'\nDeleted {len(orders)} order(s).')
    if not args.keep_balances:
        print(f'Reset balances for {len(users)} user(s) to $0.00.')
    if backup_path:
        print(f'Backup kept at {backup_path} (gitignored).')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
