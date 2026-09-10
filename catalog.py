"""
Catalog loading and filtering.

The catalog lives in the `products` database table, not in the CSV. The CSV is
only an import format now - the scraper writes one, an owner uploads it from the
Catalog Manager page, and day-to-day price and stock edits happen in the app.

The row-building rules live in catalog_rows.py, which has no pandas so the write
API can import them too. They are re-exported here because app.py, sync_catalog
and the tests have always imported them from this module.
"""

from pathlib import Path

import pandas as pd
import runtime

from config import CATALOG_CSV
from db import count_products, get_products, record_catalog_import, upsert_products
from catalog_rows import (  # noqa: F401 - re-exported for existing callers
    APPAREL_SIZES,
    BALL_WEIGHTS,
    HOLDING_PAGE_NAMES,
    REQUIRED_CSV_COLUMNS,
    SLUG_CATEGORY_HINTS,
    categories_from_url,
    classify_product_type,
    get_option_config,
    is_holding_page_name,
    missing_csv_columns,
    parse_price,
    rows_from_records,
    sku_from_product_url,
)

CATALOG_DISPLAY_COLUMNS = [
    'product_url', 'sku', 'name', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'scent', 'image_url',
]


def rows_from_catalog_csv(df: pd.DataFrame) -> list[dict]:
    """Turn a scraper CSV into rows ready for db.upsert_products()."""
    missing = missing_csv_columns(df.columns)
    if missing:
        raise ValueError(f'Missing required catalog columns: {missing}')

    return rows_from_records(df.to_dict('records'))


def import_catalog_csv(df: pd.DataFrame, mode: str = 'refresh', updated_by: str = '') -> dict:
    rows = rows_from_catalog_csv(df)
    result = upsert_products(rows, mode=mode, updated_by=updated_by)
    record_catalog_import(mode, len(rows), updated_by)
    invalidate_catalog_cache()
    return result


@runtime.cache_resource(show_spinner='Loading catalog for the first time...')
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


@runtime.cache_data(ttl=600, show_spinner=False)
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

