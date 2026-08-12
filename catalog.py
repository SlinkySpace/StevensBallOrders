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
from db import count_products, get_products, upsert_products

CATALOG_DISPLAY_COLUMNS = [
    'product_url', 'sku', 'name', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'scent', 'image_url',
]

# The scraper's CSV columns that an import needs to see.
REQUIRED_CSV_COLUMNS = {'name', 'price', 'sku', 'image_url', 'product_url'}


def classify_product_type(row) -> str:
    main_category = str(row.get('main_category', '')).lower()
    sub_category = str(row.get('sub_category', '')).lower()
    name = str(row.get('name', '')).lower()
    if 'bowling ball' in sub_category or 'bowling-ball' in sub_category or 'bowling balls' in sub_category:
        return 'bowling_ball'
    if 'apparel' in sub_category or 'shirt' in name or 'hoodie' in name or 'jersey' in name:
        return 'apparel'
    if main_category == 'merchandise' and 'accessories' not in sub_category:
        return 'apparel'
    return 'general'


def sku_from_product_url(product_url: str) -> str:
    """
    Recover a SKU from the Storm URL slug, e.g.
    .../bowling-balls/bbmveq-equinox -> BBMVEQ

    Used to repair rows where the scraper's SKU fallback grabbed the wrong <h4>
    and stored the page's shopping-cart text instead of the real SKU.
    """
    slug = str(product_url or '').rstrip('/').split('/')[-1]
    first_token = slug.split('-')[0].strip().upper()
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
        record['product_type'] = classify_product_type(record)

        if record['name']:
            rows.append(record)

    return rows


def import_catalog_csv(df: pd.DataFrame, mode: str = 'refresh', updated_by: str = '') -> dict:
    result = upsert_products(rows_from_catalog_csv(df), mode=mode, updated_by=updated_by)
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
