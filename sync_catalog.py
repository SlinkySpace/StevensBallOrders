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

# The drift guard needs a sample worth trusting. Below this share of the
# products that could have been compared, the reported drift is treated as
# unmeasured rather than as a clean bill of health.
MIN_PRICE_COVERAGE = 0.50


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--csv', default='storm_products_tagged.csv',
                        help='scraper CSV to load (default: storm_products_tagged.csv)')
    parser.add_argument('--mode', default='replace',
                        choices=['add_new', 'refresh', 'replace'],
                        help='how to merge. replace (default) makes the catalog mirror '
                             'the file exactly, dropping anything Storm has stopped '
                             'listing; refresh updates in place and keeps manual edits')
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
    parser.add_argument('--max-new-products', type=float, default=0.50,
                        help='fail if more than this fraction of the file looks new '
                             'while the catalog is already populated, which means '
                             'matching broke (default: 0.50)')
    parser.add_argument('--keep-missing', action='store_true',
                        help='leave products absent from the file in stock. By '
                             'default they are marked out of stock, since Storm '
                             'drops discontinued items by simply not listing them.')
    parser.add_argument('--max-retire', type=float, default=0.25,
                        help='refuse to retire more than this fraction of the '
                             'catalog in one run (default: 0.25)')
    parser.add_argument('--max-delete', type=float, default=0.10,
                        help='replace mode only: fail if more than this fraction '
                             'of the stored Storm catalog is missing from the '
                             'file and would be deleted (default: 0.10)')
    parser.add_argument('--updated-by', default=os.environ.get('SYNC_ACTOR', 'scheduled sync'),
                        help='recorded against every row this touches')
    parser.add_argument('--force', action='store_true',
                        help='apply even if a guard trips. Only for a genuine bulk '
                             'price change you have already eyeballed.')
    return parser.parse_args(argv)


def evaluate_guards(rows: list[dict], existing: list[dict], args) -> tuple[list[str], dict]:
    """Return (list of guard failures, stats for reporting)."""
    # Imported here rather than at module scope: db reads config at import
    # time, and main() checks DATABASE_URL before touching it so a misconfigured
    # run refuses rather than quietly writing to the local SQLite file.
    from db import STORM_URL_MARKER

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

    # A catalog that is already populated should mostly recognise what arrives.
    # A flood of "new" products means matching broke, and applying it would
    # duplicate the whole catalog rather than update it.
    #
    # Count against the same keys the write will use. Storm moved their product
    # URLs, so most rows arrive under an unfamiliar URL and are matched back by
    # SKU; measuring before that resolution reported 93% new when the real
    # figure was far lower, and would have blocked every future sync.
    incoming_urls = {row['product_url'] for row in rows}
    known_urls = {str(p['product_url']) for p in existing}
    brand_new = len(incoming_urls - known_urls)
    new_fraction = (brand_new / total) if total else 0.0

    # Meaningless in replace mode, where the Storm rows are cleared first and
    # every incoming product is new by definition.
    if existing and args.mode != 'replace' and new_fraction > args.max_new_products:
        problems.append(
            f'{brand_new} of {total} rows ({new_fraction:.0%}) look like new products, '
            f'over the {args.max_new_products:.0%} limit, while the catalog already '
            f'holds {len(existing)}. Applying this would duplicate the catalog '
            'instead of updating it.'
        )

    # replace deletes what a refresh would only have retired, so the volume has
    # to be bounded here. --max-retire does that job for refresh and is not
    # consulted in replace mode; --min-rows is an absolute floor that says
    # nothing about how much of the catalog is about to vanish. A 310-row file
    # clears a 300-row floor while removing a quarter of a 424-product catalog.
    going: list[dict] = []
    stored_storm: list[dict] = []
    if args.mode == 'replace':
        stored_storm = [p for p in existing
                        if STORM_URL_MARKER in str(p['product_url']).lower()]
        arriving = {row['product_url'] for row in rows}
        going = [p for p in stored_storm if str(p['product_url']) not in arriving]
        delete_share = (len(going) / len(stored_storm)) if stored_storm else 0.0
        if stored_storm and delete_share > args.max_delete:
            problems.append(
                f'{len(going)} of {len(stored_storm)} stored Storm products '
                f'({delete_share:.0%}) are missing from this file and would be '
                f'deleted outright, over the {args.max_delete:.0%} limit. Storm '
                'delisting that much at once is far less likely than a scrape '
                'that came back short.'
            )

    drift = (len(changed) / compared) if compared else 0.0
    if compared and drift > args.max_price_drift:
        problems.append(
            f'{len(changed)} of {compared} matched products ({drift:.0%}) changed price, '
            f'over the {args.max_price_drift:.0%} limit. If the scraper session expired '
            'these will be retail prices, not sponsor prices. Check a few against the '
            'site before applying.'
        )

    # A drift check that compared almost nothing is a measurement failure, not a
    # pass. The guard exists to catch a logged-out scrape pricing the catalog at
    # retail, and it cannot do that on a sample of six - but it reports 0% drift
    # and reads as healthy. Storm has already moved their URLs once, which is
    # exactly what shrinks this sample without anything else looking wrong.
    expected = min(total, len(existing))
    if existing and expected and compared < expected * MIN_PRICE_COVERAGE:
        problems.append(
            f'Only {compared} of a possible {expected} products could have their '
            f'price compared ({compared / expected:.0%}), under the '
            f'{MIN_PRICE_COVERAGE:.0%} minimum. Too few to tell a sponsor-price '
            'scrape from a retail one, so the drift figure above means little. '
            'Matching products to the catalog has probably broken.'
        )

    stats = {
        'total': total,
        'out_of_stock': out_of_stock,
        'oos_fraction': oos_fraction,
        'compared': compared,
        'changed': changed,
        'drift': drift,
        'new': len([r for r in rows if r['product_url'] not in known_urls]),
        'going': going,
        'stored_storm': len(stored_storm),
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

    # Ask config for the effective value rather than reading the environment
    # directly: it also picks up .streamlit/secrets.toml, so an os.environ check
    # would refuse to run on a machine configured through the file instead.
    from config import DATABASE_URL

    if not DATABASE_URL:
        print('No DATABASE_URL, in the environment or in .streamlit/secrets.toml. '
              'Refusing to run against the local SQLite file by accident.',
              file=sys.stderr)
        return EXIT_ERROR

    from catalog import rows_from_catalog_csv
    from db import (
        STORM_URL_MARKER,
        _rekey_to_existing,
        get_products,
        init_db,
        record_catalog_import,
        retire_missing_products,
        upsert_products,
    )

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

    # Resolve matches up front so the report and the guards see the same
    # products the write will.
    #
    # replace deliberately keeps Storm's own URLs rather than the ones already
    # stored, so there the resolution is applied to a copy and used only to
    # answer "which stored product is this?". Skipping it entirely, as this
    # used to, left the guards comparing by literal URL: after Storm moved
    # their catalog that matched a few dozen rows out of hundreds, so the price
    # guard was judging a retail-price scrape on a sample far too small to fail
    # on, and the deletion report called re-keyed products "deleted".
    if args.mode == 'replace':
        resolved = _rekey_to_existing([dict(row) for row in rows])
    else:
        rows = _rekey_to_existing(rows)
        resolved = rows

    print(f'Sync check for {args.csv} (mode: {args.mode})')
    problems, stats = evaluate_guards(resolved, existing, args)
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

    # Always show what disappears, whichever mode is in play. In replace mode
    # these rows are deleted outright, so seeing them before approving matters
    # more here than it did when they were merely marked out of stock.
    if args.mode != 'add_new':
        incoming = {row['product_url'] for row in resolved}
        storm_rows = [p for p in existing
                      if STORM_URL_MARKER in str(p['product_url']).lower()]
        going = [p for p in storm_rows if str(p['product_url']) not in incoming]

        if args.mode == 'refresh' and not args.keep_missing:
            going = [p for p in going if p['in_stock']]
            verb, consequence = 'marked out of stock', 'kept, with price and category intact'
        elif args.mode == 'replace':
            verb, consequence = 'deleted', 'removed from the catalog entirely'
            # Counted against resolved identity, so a product that merely moved
            # to a new Storm URL is not reported as a deletion. Counting raw
            # URLs called 407 of 460 products doomed when 36 were, which is the
            # kind of figure that gets a real warning ignored.
            moved = len([r for r in resolved if r['product_url'] in
                         {str(p['product_url']) for p in storm_rows}])
            print(f'\n  {moved} product(s) in this file matched a stored product '
                  'and will be re-keyed to their current Storm URL, not deleted.')
        else:
            going = []
            verb = consequence = ''

        if going:
            share = len(going) / len(storm_rows) if storm_rows else 0
            print(f'\n  {len(going)} Storm product(s) ({share:.0%}) are in the catalog but '
                  f'not in this file. They will be {verb} - {consequence}:')
            for product in going[:8]:
                print(f'    {str(product["name"])[:44]:<44} {str(product["sku"] or "-")[:12]}')
            if len(going) > 8:
                print(f'    ... and {len(going) - 8} more')
            hand_added = len(existing) - len(storm_rows)
            if hand_added:
                print(f'  {hand_added} hand-added product(s) are untouched.')

    if args.dry_run:
        print('\nDry run, nothing written.')
        return EXIT_OK

    result = upsert_products(rows, mode=args.mode, updated_by=args.updated_by)
    record_catalog_import(args.mode, len(rows), args.updated_by)

    print(f'\nApplied: {result["inserted"]} added, {result["updated"]} updated, '
          f'{result["skipped"]} left alone, {result["deleted"]} removed.')

    # Storm delists a discontinued product rather than marking it unavailable,
    # so anything it no longer lists has to be retired here or it stays
    # orderable forever.
    #
    # Only safe because the guards above have already established this scrape is
    # complete: on a truncated run every product it missed would look
    # discontinued. The second limit catches the case where the guards pass but
    # the file still covers far less of the catalog than it should.
    if not args.keep_missing and args.mode != 'replace':
        retired = retire_missing_products(
            [row['product_url'] for row in rows], updated_by=args.updated_by
        )
        share = len(retired) / len(existing) if existing else 0

        if share > args.max_retire:
            print(f'\nWARNING: {len(retired)} of {len(existing)} products ({share:.0%}) '
                  f'were missing from this file, over the {args.max_retire:.0%} limit. '
                  'They have been marked out of stock, but that many disappearing at '
                  'once usually means an incomplete scrape rather than a cull - worth '
                  'checking the catalog before the team next orders.')
        elif retired:
            print(f'\nRetired {len(retired)} product(s) Storm no longer lists '
                  '(marked out of stock, not deleted):')
            for product in retired[:10]:
                print(f'    {str(product["name"])[:44]:<44} {str(product["sku"] or "-")[:12]}')
            if len(retired) > 10:
                print(f'    ... and {len(retired) - 10} more')

    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
