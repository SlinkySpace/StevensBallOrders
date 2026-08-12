"""
Push a scraper CSV into the products table, with guards.

Used by the scheduled GitHub Actions refresh, and runnable by hand.

The failure this is built around: storm_auth_state.json expires. When it does,
the scraper still completes - it just sees stormbowling.com as a logged-out
visitor, which means *retail* prices instead of the team's sponsor prices, or no
prices at all. Writing that to the database would silently overcharge everyone,
and nobody would necessarily notice.

So a sync refuses to apply when the incoming data looks wrong:

  * too few rows           - the scrape broke partway through
  * too much price drift   - the classic sign of a logged-out scrape
  * a stock collapse       - prices vanished, so everything reads out of stock

Any tripped guard exits non-zero without writing, which fails the workflow and
opens an issue rather than corrupting the catalog.

Usage:
    python sync_catalog.py --dry-run
    python sync_catalog.py --mode refresh
    python sync_catalog.py --mode refresh --max-price-drift 0.35   # after a real price update
"""

import argparse
import os
import sys

import pandas as pd

EXIT_OK = 0
EXIT_GUARD_TRIPPED = 2
EXIT_ERROR = 3

# A price is "changed" only past this, so float noise isn't drift.
PRICE_EPSILON = 0.01


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--csv', default='storm_products_tagged.csv',
                        help='scraper CSV to load (default: storm_products_tagged.csv)')
    parser.add_argument('--mode', default='refresh',
                        choices=['add_new', 'refresh', 'replace'],
                        help='how to merge (default: refresh, which keeps hidden products hidden)')
    parser.add_argument('--dry-run', action='store_true',
                        help='run every check and report, but write nothing')
    parser.add_argument('--min-rows', type=int, default=300,
                        help='fail if the CSV has fewer usable rows (default: 300)')
    parser.add_argument('--max-price-drift', type=float, default=0.25,
                        help='fail if more than this fraction of matched products '
                             'changed price (default: 0.25)')
    parser.add_argument('--max-out-of-stock', type=float, default=0.40,
                        help='fail if more than this fraction of the file is out of '
                             'stock (default: 0.40)')
    parser.add_argument('--updated-by', default=os.environ.get('SYNC_ACTOR', 'scheduled sync'),
                        help='recorded against every row this touches')
    parser.add_argument('--force', action='store_true',
                        help='apply even if a guard trips. Only for a genuine bulk '
                             'price change you have already eyeballed.')
    return parser.parse_args(argv)


def evaluate_guards(rows: list[dict], existing: list[dict], args) -> tuple[list[str], dict]:
    """Return (list of guard failures, stats for reporting)."""
    problems: list[str] = []

    total = len(rows)
    out_of_stock = sum(1 for r in rows if not r['in_stock'])
    oos_fraction = (out_of_stock / total) if total else 1.0

    if total < args.min_rows:
        problems.append(
            f'Only {total} usable rows, expected at least {args.min_rows}. '
            'The scrape probably broke partway through.'
        )

    if oos_fraction > args.max_out_of_stock:
        problems.append(
            f'{out_of_stock} of {total} rows ({oos_fraction:.0%}) have no price. '
            'That usually means the scraper was not logged in.'
        )

    # Price drift against what's already stored.
    known = {
        str(p['product_url']): float(p['price'] or 0)
        for p in existing
        if float(p['price'] or 0) > 0
    }
    compared = 0
    changed = []
    for row in rows:
        old = known.get(row['product_url'])
        # Only compare where both sides have a real price; an out-of-stock scrape
        # legitimately reports 0 and doesn't overwrite the stored price.
        if old is None or row['price'] <= 0:
            continue
        compared += 1
        if abs(row['price'] - old) > PRICE_EPSILON:
            changed.append((row['name'], old, row['price']))

    drift = (len(changed) / compared) if compared else 0.0
    if compared and drift > args.max_price_drift:
        problems.append(
            f'{len(changed)} of {compared} matched products ({drift:.0%}) changed price, '
            f'over the {args.max_price_drift:.0%} limit. If the scraper session expired '
            'these will be retail prices, not sponsor prices. Check a few against the '
            'site before applying.'
        )

    stats = {
        'total': total,
        'out_of_stock': out_of_stock,
        'oos_fraction': oos_fraction,
        'compared': compared,
        'changed': changed,
        'drift': drift,
        'new': len([r for r in rows if r['product_url'] not in {str(p['product_url']) for p in existing}]),
    }
    return problems, stats


def report(stats: dict, existing_count: int) -> None:
    print(f'  rows in file          {stats["total"]}')
    print(f'  already in catalog    {existing_count}')
    print(f'  new products          {stats["new"]}')
    print(f'  out of stock in file  {stats["out_of_stock"]} ({stats["oos_fraction"]:.0%})')
    print(f'  prices compared       {stats["compared"]}')
    print(f'  prices changed        {len(stats["changed"])} ({stats["drift"]:.0%})')

    if stats['changed']:
        print('\n  price changes (first 15):')
        for name, old, new in stats['changed'][:15]:
            direction = 'up' if new > old else 'down'
            print(f'    {name[:44]:<44} ${old:>8,.2f} -> ${new:>8,.2f}  {direction}')
        if len(stats['changed']) > 15:
            print(f'    ... and {len(stats["changed"]) - 15} more')


def main(argv=None) -> int:
    args = parse_args(argv)

    if not os.environ.get('DATABASE_URL'):
        print('DATABASE_URL is not set. Refusing to run against the local SQLite '
              'file by accident.', file=sys.stderr)
        return EXIT_ERROR

    # Imported here so the DATABASE_URL check above happens first; config reads
    # the environment at import time.
    from catalog import rows_from_catalog_csv
    from db import get_products, init_db, record_catalog_import, upsert_products

    try:
        frame = pd.read_csv(args.csv)
    except Exception as exc:
        print(f'Could not read {args.csv}: {exc}', file=sys.stderr)
        return EXIT_ERROR

    try:
        rows = rows_from_catalog_csv(frame)
    except ValueError as exc:
        print(f'{args.csv} is not a usable catalog file: {exc}', file=sys.stderr)
        return EXIT_ERROR

    init_db()
    existing = get_products()

    print(f'Sync check for {args.csv} (mode: {args.mode})')
    problems, stats = evaluate_guards(rows, existing, args)
    report(stats, len(existing))

    if problems:
        print('\nGUARDS TRIPPED:')
        for problem in problems:
            print(f'  - {problem}')

        if not args.force:
            print('\nNothing was written. If these numbers are genuinely correct, '
                  're-run with --force, or import the CSV by hand from the Catalog '
                  'Manager where you can preview the diff.')
            return EXIT_GUARD_TRIPPED
        print('\n--force given, applying anyway.')

    if args.dry_run:
        print('\nDry run, nothing written.')
        return EXIT_OK

    result = upsert_products(rows, mode=args.mode, updated_by=args.updated_by)
    record_catalog_import(args.mode, len(rows), args.updated_by)

    print(f'\nApplied: {result["inserted"]} added, {result["updated"]} updated, '
          f'{result["skipped"]} left alone, {result["deleted"]} removed.')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
