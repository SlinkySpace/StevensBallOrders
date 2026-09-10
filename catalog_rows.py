"""
Turning scraper CSV rows into product rows, without pandas.

This is the half of catalog.py that never needed a DataFrame. It lives apart so
the write API can import it: api/requirements.txt deliberately omits pandas to
keep the serverless bundle small and its cold start under a second, and the
Catalog Manager's CSV import has to run there.

Splitting it is what keeps there being one implementation. The rules below are
scar tissue - ball-compare URLs that once became 61 products, holding pages that
renamed real ones, label_cleaning mislabelling moved products - and a second
copy of them in TypeScript would drift from this one the first time Storm
changed anything.
"""

import re
from typing import Iterable, Mapping
from urllib.parse import urlparse

from config import BALL_WEIGHTS, APPAREL_SIZES

# The scraper's CSV columns that an import needs to see.
REQUIRED_CSV_COLUMNS = {'name', 'price', 'sku', 'image_url', 'product_url'}


# Storm moved products to root-level URLs whose slug names the category, e.g.
# /storm-equinox-solid-bowling-ball. Those carry no category in the path, so the
# slug is the only reliable signal - and getting it wrong matters: product_type
# decides whether a shopper gets a weight selector, and drives the pending-ball
# count the batch email depends on.
SLUG_CATEGORY_HINTS = (
    ('bowling-ball', 'bowling_ball', 'Equipment', 'Bowling Balls'),
    ('-ball-roller', 'general', 'Equipment', 'Bowling Bags'),
    ('-ball-tote', 'general', 'Equipment', 'Bowling Bags'),
    ('-bowling-bag', 'general', 'Equipment', 'Bowling Bags'),
    ('-shoe', 'general', 'Equipment', 'Shoes'),
    ('-tee', 'apparel', 'Merchandise', 'Apparel'),
    ('-hoodie', 'apparel', 'Merchandise', 'Apparel'),
    ('-jersey', 'apparel', 'Merchandise', 'Apparel'),
    ('-hat', 'general', 'Merchandise', 'Accessories'),
    ('-towel', 'general', 'Bowling Essentials', 'Towels'),
    ('-glove', 'general', 'Equipment', 'Supports & Gloves'),
)


def categories_from_url(product_url: str):
    """
    Best guess at (product_type, main_category, sub_category) from a URL slug,
    or None when the slug says nothing useful.
    """
    slug = str(product_url or '').rstrip('/').split('/')[-1].lower()
    if not slug:
        return None
    for marker, product_type, main_category, sub_category in SLUG_CATEGORY_HINTS:
        if marker in slug:
            return product_type, main_category, sub_category
    return None


def classify_product_type(row) -> str:
    main_category = str(row.get('main_category', '')).lower()
    sub_category = str(row.get('sub_category', '')).lower()
    name = str(row.get('name', '')).lower()

    if 'bowling ball' in sub_category or 'bowling-ball' in sub_category or 'bowling balls' in sub_category:
        return 'bowling_ball'

    # The path said nothing useful; fall back to the slug.
    hint = categories_from_url(row.get('product_url'))
    if hint and (not sub_category or sub_category == 'unknown'):
        return hint[0]
    if hint and hint[0] == 'bowling_ball':
        return 'bowling_ball'

    if 'apparel' in sub_category or 'shirt' in name or 'hoodie' in name or 'jersey' in name:
        return 'apparel'
    if main_category == 'merchandise' and 'accessories' not in sub_category:
        return 'apparel'
    return 'general'


def sku_from_product_url(product_url: str) -> str:
    """
    Recover a SKU from an old-style catalog URL, e.g.
    /products/equipment/bowling-balls/bbmveq-equinox -> BBMVEQ

    Only that layout puts the SKU at the front of the slug. Storm's newer
    root-level URLs are descriptive - /storm-clear-storm-teal-bowling-ball - and
    reading the first token there invents a brand name instead: 116 products
    collapsed onto 9 "SKUs", with BALL covering 61 of them and STORM 36. An
    empty SKU is far better than a colliding one, since matching treats a
    duplicate SKU as no match at all.
    """
    parts = [p for p in urlparse(str(product_url or '')).path.split('/') if p]
    if len(parts) < 4 or parts[0] != 'products':
        return ''

    first_token = parts[-1].split('-')[0].strip().upper()
    return first_token if first_token.isalnum() else ''


def parse_price(raw) -> tuple[float, bool]:
    """
    Return (price, in_stock). The scraper writes the literal 'OUT_OF_STOCK' into
    the price column when a product has no purchasable price on the page.
    """
    text = str(raw or '').strip()
    if not text or text.upper() == 'OUT_OF_STOCK':
        return 0.0, False

    cleaned = re.sub(r'[^0-9.]', '', text)
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0, False

    return (value, True) if value > 0 else (0.0, False)


# Kept in step with storm_scraper.THROTTLE_MARKERS, but deliberately duplicated
# rather than imported: the scraper pulls in Playwright.
HOLDING_PAGE_NAMES = ('busy in processing', 'please wait', 'too many requests',
                      'access denied', 'are you a robot')


def is_holding_page_name(name: str) -> bool:
    """True when a scraped 'product name' is really an interstitial page."""
    lowered = str(name or '').strip().lower()
    return any(marker in lowered for marker in HOLDING_PAGE_NAMES)


def get_option_config(product_type: str):
    if product_type == 'bowling_ball':
        return {'option_type': 'Weight', 'options': BALL_WEIGHTS}
    if product_type == 'apparel':
        return {'option_type': 'Size', 'options': APPAREL_SIZES}
    return {'option_type': '', 'options': []}


def rows_from_records(records: Iterable[Mapping]) -> list[dict]:
    """
    Turn scraper CSV records into rows ready for db.upsert_products().

    Takes anything dict-shaped, so a csv.DictReader and a DataFrame's
    to_dict('records') both work.
    """
    rows = []
    seen: set[str] = set()

    for raw in records:
        product_url = str(raw.get('product_url') or '').strip()
        if not product_url or product_url in seen:
            continue

        # A product is addressed by path alone. Storm's ball comparison tool
        # links out as /ball-compare?item1=BBMVXA once per ball, and an earlier
        # scrape stored 61 of those as products. The scraper no longer follows
        # them, but any CSV written before that fix still carries them - and an
        # import is the wrong place to trust the file.
        if '?' in product_url:
            continue

        seen.add(product_url)

        sku = str(raw.get('sku') or '').strip()
        # A real SKU never contains whitespace; anything that does is scraper junk.
        if not sku or re.search(r'\s', sku) or sku.lower() == 'nan':
            sku = sku_from_product_url(product_url)

        price, in_stock = parse_price(raw.get('price'))

        record = {
            'product_url': product_url,
            'sku': sku,
            'name': str(raw.get('name') or '').strip(),
            'price': price,
            'in_stock': in_stock,
            'is_visible': True,
            'main_category': str(raw.get('main_category') or 'Unknown').strip(),
            'sub_category': str(raw.get('sub_category') or 'Unknown').strip(),
            'scent': str(raw.get('scent') or '').strip().replace('nan', ''),
            'image_url': str(raw.get('image_url') or '').strip().replace('nan', ''),
        }

        # A moved product's URL carries no category, and label_cleaning fills the
        # gap from whatever row came before - which labelled bowling balls as
        # "Apparel". Prefer what the slug actually says.
        hint = categories_from_url(product_url)
        if hint and str(raw.get('product_url', '')).count('/') <= 3:
            _, main_guess, sub_guess = hint
            record['main_category'] = main_guess
            record['sub_category'] = sub_guess

        record['product_type'] = classify_product_type(record)

        # Storm serves a "Busy in processing" holding page under load, and a
        # scrape that reads it gets that text as the product name. The scraper
        # retries and skips these now, but two such rows reached the catalog
        # before it did, replacing real products with a price of OUT_OF_STOCK.
        # An import is the wrong place to trust the file: refusing them here
        # means no future variation of that page can rename a product either.
        if is_holding_page_name(record['name']):
            continue

        if record['name']:
            rows.append(record)

    return rows


def missing_csv_columns(columns: Iterable[str]) -> list[str]:
    """The REQUIRED_CSV_COLUMNS a file does not have, sorted."""
    return sorted(REQUIRED_CSV_COLUMNS - set(columns))
