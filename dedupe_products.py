"""
Find and remove duplicate products.

Storm moved their catalog to new URLs, and a sync that keyed on URL inserted a
second copy of products it failed to recognise. This finds products that are the
same item under two rows and removes the weaker copy.

Nothing is deleted without showing you the pairs first, and orders are never
touched - they store their own copy of the product details, so removing a
catalog row cannot affect order history.

Which copy is kept, in order of preference:
  1. the one with a real SKU (a blank SKU cannot be matched to anything later)
  2. the one an admin has edited, since that edit was deliberate
  3. the one whose image file actually exists
  4. the older row

Usage:
    python dedupe_products.py --dry-run     # list the pairs, change nothing
    python dedupe_products.py               # list, then ask before deleting
    python dedupe_products.py --yes         # no prompt, for scripting
    python dedupe_products.py --hide        # hide the duplicates instead of deleting
"""

import argparse
import os
import re
import sys
from collections import defaultdict

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_ERROR = 3
CONFIRM_WORD = 'DELETE'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='report only')
    parser.add_argument('--yes', action='store_true', help='skip the confirmation')
    parser.add_argument('--hide', action='store_true',
                        help='mark duplicates invisible rather than deleting them')
    parser.add_argument('--local', action='store_true',
                        help='operate on the local SQLite file instead of DATABASE_URL')
    return parser.parse_args(argv)


def normalize_name(name: str) -> str:
    """Collapse case, punctuation and spacing so near-identical names group."""
    cleaned = re.sub(r'[^a-z0-9]+', ' ', str(name or '').lower())
    return ' '.join(cleaned.split())


def score(product: dict) -> tuple:
    """Higher sorts first, so the best copy to keep comes out in front."""
    has_sku = bool(real_sku(product))
    edited = str(product.get('updated_by') or '').strip().lower()
    hand_edited = bool(edited) and edited not in {
        'initial import', 'scheduled refresh', 'scheduled sync', 'seed', 'reimport',
    }
    image = str(product.get('image_url') or '').strip()
    has_image = bool(image) and (
        image.startswith('http') or not image.startswith('static/') or os.path.exists(image)
    )
    # Negative id so that, all else equal, the lower (older) id wins.
    return (has_sku, hand_edited, has_image, -int(product.get('id', 0)))


def is_invented_sku(product: dict) -> bool:
    """
    True when this SKU was manufactured from the URL rather than read off the page.

    The earlier sku_from_product_url took the first hyphen-token of the slug.
    Under the old layout that was the SKU (/products/.../bbmveq-equinox ->
    BBMVEQ), but on Storm's descriptive root-level URLs it yields the brand:
    /storm-iq-tour-78u-bowling-ball -> STORM, /master-tape-white -> MASTER.
    Those values are sitting in the database now.

    The test is exact, because it reproduces how they were made: the SKU equals
    the first token of a root-level slug. Real SKUs only lead a slug under
    /products/..., where the URL has four segments, so this cannot catch one.
    """
    sku = str(product.get('sku') or '').strip().upper()
    if not sku:
        return False

    from urllib.parse import urlparse
    parts = [p for p in urlparse(str(product.get('product_url') or '')).path.split('/') if p]
    if len(parts) != 1:
        return False

    return sku == parts[0].split('-')[0].strip().upper()


def real_sku(product: dict) -> str:
    """The SKU only when it actually identifies the product."""
    sku = str(product.get('sku') or '').strip().upper()
    if not sku or any(ch.isspace() for ch in sku):
        return ''
    if is_invented_sku(product):
        return ''
    return sku


def is_junk(product: dict) -> bool:
    """
    Rows that are not products at all.

    The listing scan briefly followed /ball-compare?item1=BBMVXA, one link per
    ball, and stored 61 of them - every one titled "Company" with no SKU and no
    price. Product pages never carry a query string, which identifies them
    exactly.
    """
    return '?' in str(product.get('product_url') or '')


def find_duplicates(products: list[dict]) -> tuple[list[tuple[dict, list[dict]]], list[list[dict]]]:
    """
    Return (mergeable duplicates, groups needing a human).

    Two rows are the same product only if they do not claim different SKUs.
    Storm sells distinct colourways under one name - the 3-Ball Rolling Thunder
    Signature is 37135 in white/blue and 37136 in black opal - and merging those
    would delete a real product. Any group holding more than one distinct SKU is
    handed back for review instead.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for product in products:
        if is_junk(product):
            continue
        key = normalize_name(product.get('name'))
        if key:
            groups[key].append(product)

    mergeable, ambiguous = [], []
    for members in groups.values():
        if len(members) < 2:
            continue
        distinct_skus = {real_sku(m) for m in members if real_sku(m)}
        if len(distinct_skus) > 1:
            ambiguous.append(sorted(members, key=lambda m: real_sku(m)))
            continue
        ranked = sorted(members, key=score, reverse=True)
        mergeable.append((ranked[0], ranked[1:]))

    mergeable.sort(key=lambda pair: pair[0]['name'].lower())
    ambiguous.sort(key=lambda members: members[0]['name'].lower())
    return mergeable, ambiguous


def main(argv=None) -> int:
    args = parse_args(argv)

    # config also reads .streamlit/secrets.toml, so checking os.environ alone
    # would refuse to run on a machine configured through the file.
    from config import DATABASE_URL as CONFIGURED_URL

    if not args.local and not CONFIGURED_URL:
        print('No DATABASE_URL, in the environment or .streamlit/secrets.toml. '
              'Set one, or pass --local for the local file.', file=sys.stderr)
        return EXIT_ERROR

    if args.local:
        # Blanking the environment is not enough when the URL came from
        # secrets.toml: db binds config at import time, so clear it there first
        # or --local would still operate on production.
        import config
        config.DATABASE_URL = ''
        os.environ.pop('DATABASE_URL', None)

    from catalog import invalidate_catalog_cache
    from db import delete_products, get_products, init_db, update_products

    init_db()
    products = get_products()
    junk = [p for p in products if is_junk(p)]
    duplicates, ambiguous = find_duplicates(products)

    if not duplicates and not junk:
        print(f'Nothing to clean up among {len(products)} products.')
        if ambiguous:
            print(f'({len(ambiguous)} same-name group(s) left alone - see below.)')
        else:
            return EXIT_OK

    if junk:
        print(f'{len(junk)} row(s) that are not products at all '
              '(a URL with a query string, from the ball-compare links):')
        for product in junk[:5]:
            print(f"     {str(product['name'])[:28]:<28} {product['product_url'][-52:]}")
        if len(junk) > 5:
            print(f'     ... and {len(junk) - 5} more')
        print()

    losers = [p for _, extras in duplicates for p in extras] + junk
    print(f'{len(duplicates)} duplicated product(s) among {len(products)} rows; '
          f'{len(losers)} row(s) would be {"hidden" if args.hide else "deleted"} in total.\n')

    for keeper, extras in duplicates:
        print(f"  {keeper['name'][:52]}")
        print(f"     keep  sku={str(keeper['sku'] or '-')[:14]:<14} "
              f"${float(keeper['price'] or 0):>8,.2f}  {keeper['product_url'][-46:]}")
        for extra in extras:
            print(f"     drop  sku={str(extra['sku'] or '-')[:14]:<14} "
                  f"${float(extra['price'] or 0):>8,.2f}  {extra['product_url'][-46:]}")

    if ambiguous:
        print(f'\n  Left alone - same name but different SKUs, so probably distinct '
              f'products ({len(ambiguous)} group(s)):')
        for members in ambiguous:
            print(f"     {members[0]['name'][:46]}")
            for m in members:
                print(f"        sku={str(m['sku'] or '-')[:14]:<14} "
                      f"${float(m['price'] or 0):>8,.2f}")
        print('     Merge any of these by hand in the Catalog Manager if they '
              'really are the same item.')

    if args.dry_run:
        print('\nDry run, nothing changed.')
        return EXIT_OK

    if not args.yes:
        print()
        reply = input(f'Type {CONFIRM_WORD} to confirm, anything else to abort: ')
        if reply.strip() != CONFIRM_WORD:
            print('Aborted. Nothing was changed.')
            return EXIT_ABORTED

    urls = [p['product_url'] for p in losers]
    if args.hide:
        update_products([{'product_url': u, 'is_visible': False} for u in urls],
                        updated_by='dedupe')
        print(f'\nHid {len(urls)} duplicate row(s).')
    else:
        delete_products(urls)
        print(f'\nDeleted {len(urls)} duplicate row(s).')

    # Rows that survive can still carry a manufactured SKU. Left in place it
    # would keep matching the wrong things on every future sync, so blank it -
    # no SKU is honest, and the next scrape can fill in the real one.
    dropped = {p['product_url'] for p in losers}
    stale = [p for p in get_products()
             if p['product_url'] not in dropped and is_invented_sku(p)]
    if stale:
        update_products([{'product_url': p['product_url'], 'sku': ''} for p in stale],
                        updated_by='dedupe')
        print(f'Cleared {len(stale)} invented SKU(s) (STORM, MASTER, ROTO and the like).')

    invalidate_catalog_cache()
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
