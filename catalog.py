from functools import lru_cache
from pathlib import Path

import pandas as pd

from config import CATALOG_CSV, BALL_WEIGHTS, APPAREL_SIZES


@lru_cache(maxsize=1)
def load_catalog() -> pd.DataFrame:
    csv_path = Path(CATALOG_CSV)
    if not csv_path.exists():
        raise FileNotFoundError(f'Catalog CSV not found: {csv_path}')

    df = pd.read_csv(csv_path)
    required = {'name', 'price', 'sku', 'image_url', 'product_url', 'main_category', 'sub_category'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'Missing required catalog columns: {sorted(missing)}')

    df = df.copy()
    df['name'] = df['name'].fillna('').astype(str).str.strip()
    df['sku'] = df['sku'].fillna('').astype(str).replace('nan', '').str.strip()
    df['image_url'] = df['image_url'].fillna('').astype(str).replace('nan', '').str.strip()
    df['product_url'] = df['product_url'].fillna('').astype(str).replace('nan', '').str.strip()
    df['main_category'] = df['main_category'].fillna('Unknown').astype(str).str.strip()
    df['sub_category'] = df['sub_category'].fillna('Unknown').astype(str).str.strip()

    df['price'] = df['price'].astype(str).str.strip()
    df = df[df['price'].str.upper() != 'OUT_OF_STOCK'].copy()
    df['price_value'] = pd.to_numeric(df['price'].replace('[^0-9.]', '', regex=True), errors='coerce')
    df = df[df['price_value'].notna()].copy()
    df['product_type'] = df.apply(classify_product_type, axis=1)
    return df.reset_index(drop=True)


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


def get_filter_options(df: pd.DataFrame):
    mains = ['All'] + sorted(df['main_category'].dropna().unique().tolist())
    subs = ['All'] + sorted(df['sub_category'].dropna().unique().tolist())
    return mains, subs


def filter_catalog(df: pd.DataFrame, search: str, main_category: str, sub_category: str) -> pd.DataFrame:
    result = df.copy()
    if main_category != 'All':
        result = result[result['main_category'] == main_category]
    if sub_category != 'All':
        result = result[result['sub_category'] == sub_category]
    if search:
        needle = search.strip().lower()
        result = result[
            result['name'].astype(str).str.lower().str.contains(needle, na=False)
            | result['sku'].astype(str).str.lower().str.contains(needle, na=False)
        ]
    return result.reset_index(drop=True)


def get_option_config(product_type: str):
    if product_type == 'bowling_ball':
        return {'option_type': 'Weight', 'options': BALL_WEIGHTS}
    if product_type == 'apparel':
        return {'option_type': 'Size', 'options': APPAREL_SIZES}
    return {'option_type': '', 'options': []}
