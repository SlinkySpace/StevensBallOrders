"""
Catalog loading and filtering.

The catalog lives in the `products` database table, not in the CSV. The CSV is
only an import format now - the scraper writes one, an owner uploads it from the
Catalog Manager page, and day-to-day price and stock edits happen in the app.
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from config import CATALOG_CSV, BALL_WEIGHTS, APPAREL_SIZES
from db import count_products, get_products, record_catalog_import, upsert_products

CATALOG_DISPLAY_COLUMNS = [
    'product_url', 'sku', 'name', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'scent', 'image_url',
]

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
    from urllib.parse import urlparse

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
# rather than imported: catalog.py is loaded by the Streamlit app, and the
# scraper pulls in Playwright.
HOLDING_PAGE_NAMES = ('busy in processing', 'please wait', 'too many requests',
                      'access denied', 'are you a robot')


def is_holding_page_name(name: str) -> bool:
    """True when a scraped 'product name' is really an interstitial page."""
    lowered = str(name or '').strip().lower()
    return any(marker in lowered for marker in HOLDING_PAGE_NAMES)


def rows_from_catalog_csv(df: pd.DataFrame) -> list[dict]:
    """Turn a scraper CSV into rows ready for db.upsert_products()."""
    missing = REQUIRED_CSV_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Missing required catalog columns: {sorted(missing)}')

    df = df.copy()
    for column, default in (
        ('scent', ''), ('main_category', 'Unknown'), ('sub_category', 'Unknown'),
    ):
        if column not in df.columns:
            df[column] = default

    rows = []
    seen: set[str] = set()

    for _, raw in df.iterrows():
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


def import_catalog_csv(df: pd.DataFrame, mode: str = 'refresh', updated_by: str = '') -> dict:
    rows = rows_from_catalog_csv(df)
    result = upsert_products(rows, mode=mode, updated_by=updated_by)
    record_catalog_import(mode, len(rows), updated_by)
    invalidate_catalog_cache()
    return result


@st.cache_resource(show_spinner='Loading catalog for the first time...')
def bootstrap_catalog_from_csv() -> int:
    """
    First-run seeding: if the products table is empty and the scraper CSV is
    still sitting in the repo, load it so the app isn't blank on first deploy.

    Cached so the emptiness check costs one query per server process rather than
    one per rerun.
    """
    if count_products() > 0:
        return 0

    csv_path = Path(CATALOG_CSV)
    if not csv_path.exists():
        return 0

    result = import_catalog_csv(
        pd.read_csv(csv_path), mode='add_new', updated_by='initial import'
    )
    return int(result.get('inserted', 0))


@st.cache_data(ttl=600, show_spinner=False)
def load_catalog(admin_view: bool = False) -> pd.DataFrame:
    """
    The catalog as a DataFrame.

    Shoppers see visible, in-stock products only. The Catalog Manager passes
    admin_view=True to get everything, including hidden and out-of-stock rows.
    """
    products = get_products(
        visible_only=not admin_view,
        in_stock_only=not admin_view,
    )

    if not products:
        return pd.DataFrame(columns=CATALOG_DISPLAY_COLUMNS)

    df = pd.DataFrame(products)
    for column in CATALOG_DISPLAY_COLUMNS:
        if column not in df.columns:
            df[column] = ''

    df['price_value'] = pd.to_numeric(df['price'], errors='coerce').fillna(0.0)
    return df.reset_index(drop=True)


def invalidate_catalog_cache() -> None:
    """Call after any write to products so shoppers see the change immediately."""
    load_catalog.clear()


def get_filter_options(df: pd.DataFrame):
    if df.empty:
        return ['All'], ['All']
    mains = ['All'] + sorted(df['main_category'].dropna().unique().tolist())
    subs = ['All'] + sorted(df['sub_category'].dropna().unique().tolist())
    return mains, subs


def filter_catalog(df: pd.DataFrame, search: str, main_category: str, sub_category: str) -> pd.DataFrame:
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)
    if main_category != 'All':
        mask &= df['main_category'] == main_category
    if sub_category != 'All':
        mask &= df['sub_category'] == sub_category
    if search:
        needle = search.strip().lower()
        mask &= (
            df['name'].astype(str).str.lower().str.contains(needle, na=False, regex=False)
            | df['sku'].astype(str).str.lower().str.contains(needle, na=False, regex=False)
        )

    return df[mask].reset_index(drop=True)


def get_option_config(product_type: str):
    if product_type == 'bowling_ball':
        return {'option_type': 'Weight', 'options': BALL_WEIGHTS}
    if product_type == 'apparel':
        return {'option_type': 'Size', 'options': APPAREL_SIZES}
    return {'option_type': '', 'options': []}
