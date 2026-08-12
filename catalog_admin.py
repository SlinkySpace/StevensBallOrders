"""
Catalog Manager - the owner-facing page for editing products and stock.

This is what replaces "edit the CSV, commit, push, wait for a redeploy". Prices,
stock and visibility are rows in the database, so a change here is live for
everyone on their next page load.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from catalog import (
    import_catalog_csv,
    invalidate_catalog_cache,
    load_catalog,
    rows_from_catalog_csv,
)
from config import APPAREL_SIZES, BALL_WEIGHTS
from db import (
    EDITABLE_PRODUCT_COLUMNS,
    count_products,
    delete_products,
    get_catalog_freshness,
    set_products_stock,
    update_products,
    upsert_products,
)

PRODUCT_TYPES = ['bowling_ball', 'apparel', 'general']

# How long before an un-reimported catalog is worth flagging.
STALE_CATALOG_DAYS = 30

EDITOR_COLUMNS = [
    'image_url', 'name', 'sku', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'updated_at', 'product_url',
]

IMPORT_MODES = {
    'Add new products only': 'add_new',
    'Refresh prices, stock and details (keeps hidden products hidden)': 'refresh',
    'Replace the whole catalog': 'replace',
}


def _image_column_url(value: str) -> str:
    value = str(value or '').strip()
    if value.startswith(('http://', 'https://', 'data:')):
        return value
    if value.startswith('static/'):
        return f'app/{value}'
    return ''


def _editor_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.reindex(columns=EDITOR_COLUMNS).copy()
    frame['price'] = pd.to_numeric(frame['price'], errors='coerce').fillna(0.0)
    frame['in_stock'] = frame['in_stock'].astype(bool)
    frame['is_visible'] = frame['is_visible'].astype(bool)
    frame['image_url'] = frame['image_url'].map(_image_column_url)
    frame['updated_at'] = pd.to_datetime(frame['updated_at'], errors='coerce')
    return frame.reset_index(drop=True)


def _diff_rows(before: pd.DataFrame, after: pd.DataFrame) -> list[dict]:
    """Rows the admin actually changed, as update dicts keyed by product_url."""
    tracked = [c for c in EDITABLE_PRODUCT_COLUMNS if c in after.columns]
    updates = []

    for position, product_url in after['product_url'].items():
        if position not in before.index:
            continue

        changed = {}
        for column in tracked:
            old_value = before.at[position, column]
            new_value = after.at[position, column]

            if column == 'price':
                if round(float(old_value or 0), 2) != round(float(new_value or 0), 2):
                    changed[column] = round(float(new_value or 0), 2)
            elif column in ('in_stock', 'is_visible'):
                if bool(old_value) != bool(new_value):
                    changed[column] = bool(new_value)
            elif str(old_value or '') != str(new_value or ''):
                changed[column] = str(new_value or '')

        if changed:
            changed['product_url'] = str(product_url)
            updates.append(changed)

    return updates


def _render_editor_tab(admin_email: str) -> None:
    df = load_catalog(admin_view=True)

    if df.empty:
        st.info('No products yet. Use the "Import from scraper CSV" tab to load your catalog.')
        return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        search = st.text_input('Filter by name or SKU', key='cm_search')
    with c2:
        categories = ['All'] + sorted(df['sub_category'].dropna().unique().tolist())
        category = st.selectbox('Category', categories, key='cm_category')
    with c3:
        stock_filter = st.selectbox(
            'Stock', ['All', 'In stock only', 'Out of stock only'], key='cm_stock'
        )

    view = df
    if search:
        needle = search.strip().lower()
        view = view[
            view['name'].astype(str).str.lower().str.contains(needle, na=False, regex=False)
            | view['sku'].astype(str).str.lower().str.contains(needle, na=False, regex=False)
        ]
    if category != 'All':
        view = view[view['sub_category'] == category]
    if stock_filter == 'In stock only':
        view = view[view['in_stock'].astype(bool)]
    elif stock_filter == 'Out of stock only':
        view = view[~view['in_stock'].astype(bool)]

    if view.empty:
        st.warning('No products match that filter.')
        return

    st.caption(
        f'{len(view)} of {len(df)} products. '
        'Edit cells directly, then press "Save changes". '
        'Un-ticking **In stock** hides a product from shoppers immediately.'
    )

    original = _editor_frame(view)
    main_categories = sorted(df['main_category'].dropna().unique().tolist())
    sub_categories = sorted(df['sub_category'].dropna().unique().tolist())

    # st.data_editor remembers pending edits by row *position*. If the key stayed
    # constant while the filters changed the row order, an unsaved edit to row 3
    # would silently land on whatever product row 3 now is. Tying the key to the
    # filters discards pending edits when the visible set changes instead.
    editor_key = f'catalog_editor_{hash((search, category, stock_filter))}'

    edited = st.data_editor(
        original,
        key=editor_key,
        use_container_width=True,
        hide_index=True,
        num_rows='fixed',
        height=560,
        column_config={
            'image_url': st.column_config.ImageColumn('', width='small'),
            'name': st.column_config.TextColumn('Product', width='large', required=True),
            'sku': st.column_config.TextColumn('SKU', width='small'),
            'price': st.column_config.NumberColumn(
                'Price', min_value=0.0, step=1.0, format='$%.2f'
            ),
            'in_stock': st.column_config.CheckboxColumn('In stock'),
            'is_visible': st.column_config.CheckboxColumn(
                'Visible', help='Untick to hide from the catalog without deleting it'
            ),
            'main_category': st.column_config.SelectboxColumn(
                'Main category', options=main_categories
            ),
            'sub_category': st.column_config.SelectboxColumn(
                'Sub category', options=sub_categories
            ),
            'product_type': st.column_config.SelectboxColumn(
                'Type',
                options=PRODUCT_TYPES,
                help=(
                    'Drives the option dropdown shoppers see: '
                    f'bowling_ball -> {BALL_WEIGHTS[0]}..{BALL_WEIGHTS[-1]}, '
                    f'apparel -> {APPAREL_SIZES[0]}..{APPAREL_SIZES[-1]}, '
                    'general -> none'
                ),
            ),
            'updated_at': st.column_config.DatetimeColumn(
                'Last edited', width='small', format='MMM D, YYYY'
            ),
            'product_url': st.column_config.LinkColumn('Storm page', width='small'),
        },
        disabled=['image_url', 'updated_at', 'product_url'],
    )

    updates = _diff_rows(original, edited)

    save_col, count_col = st.columns([1, 3])
    with save_col:
        if st.button('Save changes', type='primary', disabled=not updates):
            applied = update_products(updates, updated_by=admin_email)
            invalidate_catalog_cache()
            # Drop the editor's pending-edit state so the saved values aren't
            # still sitting there as a phantom diff after the rerun.
            st.session_state.pop(editor_key, None)
            st.success(f'Updated {applied} product(s).')
            st.rerun()
    with count_col:
        if updates:
            st.info(f'{len(updates)} unsaved change(s).')

    st.divider()
    st.subheader('Bulk stock update')
    st.caption('Applies to every product currently shown by the filters above.')

    b1, b2, b3 = st.columns(3)
    shown_urls = view['product_url'].tolist()
    with b1:
        if st.button(f'Mark all {len(shown_urls)} in stock'):
            set_products_stock(shown_urls, True, updated_by=admin_email)
            invalidate_catalog_cache()
            st.success(f'{len(shown_urls)} product(s) marked in stock.')
            st.rerun()
    with b2:
        if st.button(f'Mark all {len(shown_urls)} out of stock'):
            set_products_stock(shown_urls, False, updated_by=admin_email)
            invalidate_catalog_cache()
            st.success(f'{len(shown_urls)} product(s) marked out of stock.')
            st.rerun()
    with b3:
        st.download_button(
            'Download catalog CSV',
            data=df.to_csv(index=False).encode('utf-8'),
            file_name='catalog_export.csv',
            mime='text/csv',
        )


def _render_import_tab(admin_email: str) -> None:
    st.caption(
        'Re-run `storm_scraper.py` then `label_cleaning.py` when Storm changes their '
        'line-up, and upload the resulting CSV here. No commit, no redeploy.'
    )

    uploaded = st.file_uploader('Catalog CSV', type=['csv'], key='cm_upload')
    if uploaded is None:
        return

    try:
        incoming = pd.read_csv(uploaded)
    except Exception as exc:
        st.error(f'Could not read that CSV: {exc}')
        return

    try:
        rows = rows_from_catalog_csv(incoming)
    except ValueError as exc:
        st.error(str(exc))
        return

    if not rows:
        st.warning('That file has no usable product rows.')
        return

    current = load_catalog(admin_view=True)
    current_urls = set(current['product_url']) if not current.empty else set()
    incoming_urls = {row['product_url'] for row in rows}

    new_count = len(incoming_urls - current_urls)
    matched = len(incoming_urls & current_urls)
    missing = len(current_urls - incoming_urls)

    m1, m2, m3 = st.columns(3)
    m1.metric('New products', new_count)
    m2.metric('Already in catalog', matched)
    m3.metric('In catalog but not in file', missing)

    if not current.empty and matched:
        price_lookup = dict(zip(current['product_url'], current['price']))
        changes = [
            {
                'Product': row['name'],
                'Current price': float(price_lookup[row['product_url']]),
                'New price': row['price'],
            }
            for row in rows
            if row['product_url'] in price_lookup
            and row['price'] > 0
            and round(float(price_lookup[row['product_url']]), 2) != round(row['price'], 2)
        ]
        if changes:
            with st.expander(f'{len(changes)} price change(s) in this file'):
                st.dataframe(pd.DataFrame(changes), use_container_width=True, hide_index=True)

    label = st.radio('How should this file be applied?', list(IMPORT_MODES), index=1)
    mode = IMPORT_MODES[label]

    if mode == 'replace':
        st.warning(
            'Replace deletes every product row first, including any you added by hand '
            'and any hidden/out-of-stock flags you set. Past orders are not affected.'
        )

    if st.button('Apply import', type='primary'):
        result = import_catalog_csv(incoming, mode=mode, updated_by=admin_email)
        st.success(
            f"Import complete - {result['inserted']} added, {result['updated']} updated, "
            f"{result['skipped']} left alone, {result['deleted']} removed."
        )
        st.rerun()


def _render_add_tab(admin_email: str) -> None:
    st.caption('For anything not in the Storm catalog - club shirts, raffle items, one-offs.')

    with st.form('add_product_form'):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input('Product name')
            sku = st.text_input('SKU')
            price = st.number_input('Price', min_value=0.0, step=1.0, value=0.0)
        with c2:
            main_category = st.text_input('Main category', value='Merchandise')
            sub_category = st.text_input('Sub category', value='Apparel')
            product_type = st.selectbox('Type', PRODUCT_TYPES, index=2)

        image_url = st.text_input('Image URL (optional)')
        reference = st.text_input(
            'Reference / product URL',
            help='Any unique string. Used as the product key, so make it unique.',
        )

        if st.form_submit_button('Add product', type='primary'):
            if not name.strip():
                st.error('Product name is required.')
            elif not reference.strip():
                st.error('Reference / product URL is required - it identifies the product.')
            else:
                upsert_products(
                    [{
                        'product_url': reference.strip(),
                        'sku': sku.strip(),
                        'name': name.strip(),
                        'price': float(price),
                        'in_stock': True,
                        'is_visible': True,
                        'main_category': main_category.strip() or 'Unknown',
                        'sub_category': sub_category.strip() or 'Unknown',
                        'product_type': product_type,
                        'scent': '',
                        'image_url': image_url.strip(),
                    }],
                    mode='refresh',
                    updated_by=admin_email,
                )
                invalidate_catalog_cache()
                st.success(f'Added {name.strip()}.')
                st.rerun()

    st.divider()
    st.subheader('Remove products')
    st.caption('Hiding is usually better than deleting - untick "Visible" in the Products tab.')

    df = load_catalog(admin_view=True)
    if df.empty:
        return

    labels = {
        f"{row['name']} ({row['sku'] or 'no SKU'})": row['product_url']
        for _, row in df.iterrows()
    }
    chosen = st.multiselect('Products to delete permanently', sorted(labels))
    if chosen and st.button(f'Delete {len(chosen)} product(s)', type='secondary'):
        delete_products([labels[label] for label in chosen])
        invalidate_catalog_cache()
        st.success(f'Deleted {len(chosen)} product(s).')
        st.rerun()


def _humanize_age(timestamp: str) -> tuple[str, int]:
    """Return a friendly age like '3 days ago' plus the age in days."""
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except (TypeError, ValueError):
        return 'unknown', 10**6

    delta = datetime.now() - moment
    days = max(delta.days, 0)
    if days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            return 'just now', 0
        return f'{hours} hour{"s" if hours != 1 else ""} ago', 0
    if days == 1:
        return 'yesterday', 1
    if days < 30:
        return f'{days} days ago', days
    months = days // 30
    return f'about {months} month{"s" if months != 1 else ""} ago', days


def render_freshness(freshness: dict) -> None:
    """
    Nothing keeps the catalog current automatically - Storm has no feed and the
    scraper needs a logged-in browser session. So make staleness visible instead
    of letting it pass unnoticed.
    """
    last_import = freshness.get('last_import') or {}
    imported_at = last_import.get('at')

    if not imported_at:
        st.info(
            'No scraper CSV has been imported yet. Prices and stock are whatever '
            'the catalog was seeded with.'
        )
        return

    label, days = _humanize_age(imported_at)
    detail = f"Catalog last imported **{label}**"
    if last_import.get('by'):
        detail += f" by {last_import['by']}"
    detail += f" ({last_import.get('count', '?')} products, {last_import.get('mode', '?')} mode)."

    if days >= STALE_CATALOG_DAYS:
        st.warning(
            f"{detail} Storm may have changed prices or dropped products since then - "
            'worth re-running the scraper. Day-to-day stock changes you can just '
            'make below.'
        )
    else:
        st.caption(detail)


def render_catalog_manager(admin_email: str = '') -> None:
    st.header('Catalog Manager')

    total = count_products()
    df = load_catalog(admin_view=True)
    in_stock = int(df['in_stock'].astype(bool).sum()) if not df.empty else 0
    visible = int(df['is_visible'].astype(bool).sum()) if not df.empty else 0
    freshness = get_catalog_freshness()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Products', total)
    m2.metric('In stock', in_stock)
    m3.metric('Visible to shoppers', visible)
    last_change, _ = _humanize_age(freshness.get('last_product_change'))
    m4.metric('Last edited', last_change)

    render_freshness(freshness)

    products_tab, import_tab, add_tab = st.tabs(
        ['Products', 'Import from scraper CSV', 'Add / remove']
    )
    with products_tab:
        _render_editor_tab(admin_email)
    with import_tab:
        _render_import_tab(admin_email)
    with add_tab:
        _render_add_tab(admin_email)
