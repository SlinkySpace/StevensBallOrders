import html
from pathlib import Path

import pandas as pd
import streamlit as st

from auth import (
    account_needs_password,
    change_password,
    get_current_user,
    init_session_state,
    is_admin,
    is_logged_in,
    login_user,
    logout_user,
    refresh_user_session,
    set_initial_password,
    signup_user,
)
from catalog import (
    bootstrap_catalog_from_csv,
    filter_catalog,
    get_filter_options,
    get_option_config,
    load_catalog,
)
from catalog_admin import render_catalog_manager
from config import (
    ACTIVE_ORDER_STATUSES,
    APP_TITLE,
    BASE_DIR,
    COMPLETED_ORDER_STATUSES,
    MIN_PASSWORD_LENGTH,
    TEAM_ACCESS_CODE,
)
from db import (
    clear_user_password,
    delete_order,
    evaluate_ball_batch_notification,
    get_orders_for_user,
    get_owner_dashboard_data,
    init_db,
    place_order_items,
    save_cart,
    update_all_orders_status,
    update_balance,
    update_order_status,
    update_saved_card,
)

st.set_page_config(page_title=APP_TITLE, layout='wide', page_icon='🎳')
init_db()
init_session_state()
refresh_user_session()

ORDER_STATUS_OPTIONS = ['submitted', 'approved', 'ordered', 'fulfilled', 'cancelled']
CATALOG_COLUMNS = 3
CATALOG_ITEMS_PER_PAGE = 24  # a multiple of CATALOG_COLUMNS, so rows stay full
PLACEHOLDER_IMAGE = (
    "<div class='product-image product-image--empty'>No image</div>"
)

# Typography and fixed-height blocks only. Square images plus a two-line clamp on
# the name make tiles in a row the same height on their own, so there's no
# flexbox targeting Streamlit's generated class names to break on an upgrade.
CATALOG_CSS = """
<style>
.product-image {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: contain;
    border-radius: 0.5rem;
    background: rgba(128, 128, 128, 0.05);
}
.product-image--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(128, 128, 128, 0.7);
    font-size: 0.8rem;
}
.product-name {
    font-weight: 600;
    line-height: 1.3;
    margin: 0.6rem 0 0.15rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.6em;
}
.product-price {
    font-size: 1.15rem;
    font-weight: 700;
    line-height: 1.2;
}
.product-meta {
    font-size: 0.75rem;
    opacity: 0.6;
    margin-bottom: 0.5rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
"""


def currency(value: float) -> str:
    return f"${value:,.2f}"


@st.cache_data(show_spinner=False)
def _static_image_files() -> set[str]:
    """
    Every file under static/, as posix paths relative to the app root.

    Used to tell a broken image path from a good one without stat()-ing the
    filesystem once per product card per rerun.
    """
    static_root = Path(BASE_DIR) / 'static'
    if not static_root.is_dir():
        return set()
    return {
        path.relative_to(BASE_DIR).as_posix()
        for path in static_root.rglob('*')
        if path.is_file()
    }


def image_src(image_value: str) -> str:
    """
    Resolve a stored image path to something the browser can fetch.

    Local files are served by Streamlit's static file server (enabled in
    .streamlit/config.toml) at app/static/..., which lets the browser cache them
    and skips routing every image through the server's media manager.
    """
    value = str(image_value or '').strip().replace('\\', '/')
    if not value:
        return ''
    if value.startswith(('http://', 'https://', 'data:')):
        return value
    if value.startswith('static/') and value in _static_image_files():
        return f'app/{value}'
    return ''


def show_image(image_value: str, alt: str = '') -> None:
    src = image_src(image_value)
    if not src:
        st.markdown(PLACEHOLDER_IMAGE, unsafe_allow_html=True)
        return

    # loading="lazy" means a page of products only fetches what's on screen.
    st.markdown(
        f"<img class='product-image' src='{html.escape(src, quote=True)}' "
        f"alt='{html.escape(alt, quote=True)}' loading='lazy' decoding='async' />",
        unsafe_allow_html=True,
    )


def ensure_cart():
    if 'cart' not in st.session_state or st.session_state['cart'] is None:
        st.session_state['cart'] = []


def persist_cart():
    ensure_cart()
    user = get_current_user()
    if user:
        save_cart(int(user['id']), st.session_state['cart'])


def add_to_cart(item: dict):
    ensure_cart()
    st.session_state['cart'].append(item)
    persist_cart()


def remove_cart_index(index: int):
    ensure_cart()
    st.session_state['cart'].pop(index)
    persist_cart()


def ensure_catalog_page_valid(total_pages: int) -> int:
    current = int(st.session_state.get('catalog_page_number', 1))
    current = max(1, min(current, max(1, total_pages)))
    st.session_state['catalog_page_number'] = current
    return current


@st.dialog('Confirm order deletion')
def confirm_delete_dialog(order_id: int, product_name: str):
    st.warning(f"Delete order #{order_id} for {product_name}? This cannot be undone.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button('Yes, delete order', type='primary', key=f'dialog_confirm_delete_{order_id}'):
            delete_order(order_id)
            st.session_state.pop('delete_target_order_id', None)
            st.session_state.pop('delete_target_product_name', None)
            st.success('Order deleted.')
            st.rerun()
    with c2:
        if st.button('Cancel', key=f'dialog_cancel_delete_{order_id}'):
            st.session_state.pop('delete_target_order_id', None)
            st.session_state.pop('delete_target_product_name', None)
            st.rerun()


def render_auth_page():
    st.title(APP_TITLE)
    st.caption('Internal team ordering tool for discounted bowling products.')

    login_tab, signup_tab, setup_tab = st.tabs(
        ['Login', 'Create account', 'First time here?']
    )

    with login_tab:
        with st.form('login_form'):
            email = st.text_input('Email')
            password = st.text_input('Password', type='password')
            if st.form_submit_button('Login', type='primary'):
                ok, error = login_user(email, password)
                if ok:
                    st.session_state['catalog_page_number'] = 1
                    st.rerun()
                else:
                    st.error(error)
                    if account_needs_password(email):
                        st.info(
                            'This account was created before passwords were added. '
                            'Open the **First time here?** tab to set one.'
                        )

    with signup_tab:
        with st.form('signup_form'):
            c1, c2 = st.columns(2)
            with c1:
                first_name = st.text_input('First name')
            with c2:
                last_name = st.text_input('Last name')
            email = st.text_input('Email address')
            password = st.text_input(
                'Password', type='password',
                help=f'At least {MIN_PASSWORD_LENGTH} characters.',
            )
            confirm = st.text_input('Confirm password', type='password')
            access_code = (
                st.text_input('Team access code', type='password')
                if TEAM_ACCESS_CODE else ''
            )

            if st.form_submit_button('Create account', type='primary'):
                ok, error = signup_user(
                    first_name, last_name, email, password, confirm, access_code
                )
                if ok:
                    st.session_state['catalog_page_number'] = 1
                    st.rerun()
                else:
                    st.error(error)

    with setup_tab:
        st.caption(
            'If your account was created before passwords were added, set your '
            'password here. Your orders and balance stay exactly as they are.'
        )
        with st.form('claim_form'):
            email = st.text_input('Email')
            password = st.text_input(
                'Choose a password', type='password',
                help=f'At least {MIN_PASSWORD_LENGTH} characters.',
            )
            confirm = st.text_input('Confirm password', type='password')
            access_code = (
                st.text_input('Team access code', type='password')
                if TEAM_ACCESS_CODE else ''
            )

            if st.form_submit_button('Set password and log in', type='primary'):
                ok, error = set_initial_password(email, password, confirm, access_code)
                if ok:
                    st.session_state['catalog_page_number'] = 1
                    st.rerun()
                else:
                    st.error(error)


def render_sidebar():
    user = get_current_user()
    cart = st.session_state.get('cart', [])
    cart_count = sum(int(item.get('quantity', 1)) for item in cart)
    cart_total = sum(float(i['unit_price']) * int(i['quantity']) for i in cart)

    st.sidebar.markdown(f"### 🎳 {APP_TITLE}")
    st.sidebar.caption(
        f"{user['first_name']} {user['last_name']} · {user['email']}"
    )

    # Balance is the number people actually care about, so lead with it.
    balance = float(user.get('balance_owed') or 0)
    if balance > 0:
        st.sidebar.metric('You owe', currency(balance))

    pages = {
        'Catalog': '🎳  Catalog',
        'Cart': f'🛒  Cart ({cart_count})' if cart_count else '🛒  Cart',
        'Checkout': '✅  Checkout',
        'Outstanding Orders': '📦  Outstanding Orders',
        'Order History': '🕘  Order History',
        'Profile': '👤  Profile',
    }
    if is_admin():
        pages['Owner Dashboard'] = '📊  Owner Dashboard'
        pages['Catalog Manager'] = '🗂️  Catalog Manager'

    # Keyed, so the selected page survives the st.rerun() that follows actions
    # like emptying the cart or applying a status. Without it the nav snapped
    # back to Catalog every time.
    choice = st.sidebar.radio(
        'Go to',
        list(pages),
        format_func=lambda page: pages[page],
        label_visibility='collapsed',
        key='nav_page',
    )

    if cart_count:
        st.sidebar.caption(f'Cart total: {currency(cart_total)}')

    st.sidebar.divider()
    if st.sidebar.button('Log out', use_container_width=True):
        st.session_state['catalog_page_number'] = 1
        logout_user()
        st.rerun()

    return choice


def _default_option_index(product_type: str, options: list) -> int:
    """Bowling balls default to 15 lb, everything else to the first option."""
    if product_type == 'bowling_ball':
        for i, opt in enumerate(options):
            if ''.join(ch for ch in str(opt) if ch.isdigit()) == '15':
                return i
    return 0


@st.fragment
def render_product_card(row: dict, row_key: str):
    """
    One product tile in the catalog grid.

    A fragment, so picking a weight or changing a quantity reruns this one tile
    rather than re-rendering the whole page of products.
    """
    name = str(row['name'])
    price = float(row['price_value'])
    scent = str(row.get('scent', '') or '').strip()
    is_ball = row.get('product_type') == 'bowling_ball'

    with st.container(border=True):
        show_image(row.get('image_url'), alt=name)

        st.markdown(
            f"<div class='product-name' title=\"{html.escape(name, quote=True)}\">"
            f"{html.escape(name)}</div>"
            f"<div class='product-price'>{currency(price)}</div>"
            f"<div class='product-meta'>{html.escape(str(row['sku']) or 'No SKU')}</div>",
            unsafe_allow_html=True,
        )

        option_config = get_option_config(row['product_type'])

        with st.popover('Add to cart', use_container_width=True):
            st.markdown(f"**{name}**")
            st.caption(currency(price) + (f" · {scent}" if is_ball and scent and scent.lower() != 'none' else ''))

            option_value = ''
            if option_config['options']:
                options = option_config['options']
                option_value = st.selectbox(
                    option_config['option_type'],
                    options,
                    index=_default_option_index(row['product_type'], options),
                    key=f"opt_{row_key}",
                )

            quantity = st.number_input(
                'Quantity', min_value=1, max_value=20, value=1, step=1, key=f"qty_{row_key}"
            )
            note = st.text_input('Note (optional)', key=f"note_{row_key}")

            product_url = str(row.get('product_url', '')).strip()
            if product_url.startswith(('http://', 'https://')):
                st.markdown(f"[View on stormbowling.com]({product_url})")

            if st.button('Add to cart', key=f"add_{row_key}", type='primary',
                         use_container_width=True):
                add_to_cart({
                    'name': name,
                    'sku': str(row['sku']),
                    'unit_price': price,
                    'image_url': str(row['image_url']),
                    'product_url': str(row['product_url']),
                    'option_type': option_config['option_type'],
                    'option_value': option_value,
                    'quantity': int(quantity),
                    'note': note,
                    'main_category': str(row['main_category']),
                    'sub_category': str(row['sub_category']),
                    'product_type': str(row['product_type']),
                    'scent': scent if is_ball else '',
                })
                st.toast(f'Added {name} to cart.', icon='🎳')
                # Full rerun so the sidebar cart count keeps up.
                st.rerun(scope='app')


def render_catalog_page():
    st.title('Catalog')
    df = load_catalog()

    if df.empty:
        st.info('The catalog is empty.')
        if is_admin():
            st.caption('Load it from the Catalog Manager page.')
        return

    main_options, sub_options = get_filter_options(df)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        search = st.text_input(
            'Search', placeholder='Search by product name or SKU', label_visibility='collapsed'
        )
    with c2:
        selected_main = st.selectbox('Main category', main_options, label_visibility='collapsed')
    with c3:
        selected_sub = st.selectbox('Sub category', sub_options, label_visibility='collapsed')

    filtered = filter_catalog(df, search, selected_main, selected_sub)

    total_items = len(filtered)
    if total_items == 0:
        st.warning('No products match those filters.')
        return

    total_pages = max(1, (total_items + CATALOG_ITEMS_PER_PAGE - 1) // CATALOG_ITEMS_PER_PAGE)
    current_page = ensure_catalog_page_valid(total_pages)

    start_idx = (current_page - 1) * CATALOG_ITEMS_PER_PAGE
    end_idx = min(start_idx + CATALOG_ITEMS_PER_PAGE, total_items)
    page_df = filtered.iloc[start_idx:end_idx]

    st.caption(
        f'Showing {start_idx + 1}-{end_idx} of {total_items} products'
        + (f' · page {current_page} of {total_pages}' if total_pages > 1 else '')
    )

    # Lay the page out as rows of CATALOG_COLUMNS tiles.
    rows = list(page_df.iterrows())
    for offset in range(0, len(rows), CATALOG_COLUMNS):
        columns = st.columns(CATALOG_COLUMNS, gap='medium')
        for column, (_, row) in zip(columns, rows[offset:offset + CATALOG_COLUMNS]):
            with column:
                # product_url is unique per product, so widget keys stay stable
                # across reruns even as filters and pagination change the view.
                render_product_card(row.to_dict(), str(row['product_url']))

    if total_pages > 1:
        st.divider()
        nav_left, nav_center, nav_right = st.columns([1, 2, 1])
        with nav_left:
            if st.button('← Previous', disabled=current_page <= 1,
                         key='catalog_prev_bottom', use_container_width=True):
                st.session_state['catalog_page_number'] = max(1, current_page - 1)
                st.rerun()
        with nav_center:
            st.markdown(
                f"<div style='text-align:center;padding-top:0.45rem;opacity:0.7;'>"
                f"Page {current_page} of {total_pages}</div>",
                unsafe_allow_html=True,
            )
        with nav_right:
            if st.button('Next →', disabled=current_page >= total_pages,
                         key='catalog_next_bottom', use_container_width=True):
                st.session_state['catalog_page_number'] = min(total_pages, current_page + 1)
                st.rerun()


def render_cart_page():
    st.title('Cart')
    ensure_cart()
    if not st.session_state['cart']:
        st.info('Your cart is empty. Head to the Catalog to add something.')
        return

    total = 0.0
    remove_index = None
    cart_changed = False

    for idx, item in enumerate(st.session_state['cart']):
        with st.container(border=True):
            left, right = st.columns([1, 4])
            with left:
                show_image(item.get('image_url'), alt=str(item.get('name', '')))
            with right:
                st.write(f"**{item['name']}**")
                st.write(f"SKU: {item['sku'] or 'N/A'}")

                scent = str(item.get('scent', '') or '').strip()
                if item.get('product_type') == 'bowling_ball' and scent and scent.lower() != 'none':
                    st.write(f"Scent: {scent}")

                st.write(f"Unit price: {currency(item['unit_price'])}")

                old_qty = int(item.get('quantity', 1))
                qty = st.number_input(
                    f"Quantity #{idx+1}", min_value=1, max_value=20, value=old_qty,
                    key=f"cart_qty_{idx}"
                )
                item['quantity'] = int(qty)
                if int(qty) != old_qty:
                    cart_changed = True

                if item.get('option_type'):
                    options = get_option_config(item.get('product_type', 'general'))['options']
                    current = item.get('option_value', options[0] if options else '')
                    if current not in options and options:
                        options = [current] + options

                    selected = st.selectbox(
                        item['option_type'],
                        options,
                        index=options.index(current) if options else 0,
                        key=f"cart_opt_{idx}",
                    ) if options else current

                    if selected != item.get('option_value'):
                        item['option_value'] = selected
                        cart_changed = True

                old_note = item.get('note', '')
                new_note = st.text_input('Item note', value=old_note, key=f"cart_note_{idx}")
                if new_note != old_note:
                    item['note'] = new_note
                    cart_changed = True

                if st.button('Remove item', key=f"remove_{idx}"):
                    remove_index = idx

                line_total = float(item['unit_price']) * int(item['quantity'])
                total += line_total
                st.write(f"**Line total:** {currency(line_total)}")

    if remove_index is not None:
        remove_cart_index(remove_index)
        st.rerun()

    if cart_changed:
        persist_cart()

    st.divider()
    left, right = st.columns([2, 1])
    with left:
        st.metric('Cart total', currency(total))
    with right:
        if st.button('Empty cart', use_container_width=True):
            st.session_state['cart'] = []
            persist_cart()
            st.toast('Cart emptied.')
            st.rerun()


def render_checkout_page():
    st.title('Checkout')
    ensure_cart()
    if not st.session_state['cart']:
        st.info('Add items to your cart before checkout.')
        return

    total = sum(float(item['unit_price']) * int(item['quantity']) for item in st.session_state['cart'])
    st.write('Review your order below.')
    st.table(pd.DataFrame([
        {
            'Product': item['name'],
            'SKU': item['sku'],
            'Option': f"{item.get('option_type', '')}: {item.get('option_value', '')}" if item.get('option_type') else '',
            'Qty': item['quantity'],
            'Unit Price': currency(item['unit_price']),
            'Line Total': currency(float(item['unit_price']) * int(item['quantity']))
        }
        for item in st.session_state['cart']
    ]))
    st.metric('Estimated total', currency(total))
    checkout_note = st.text_area('Checkout note (optional)')

    if st.button('Confirm and place order', type='primary'):
        user = get_current_user()
        place_order_items(user, st.session_state['cart'], checkout_note)
        st.session_state['cart'] = []
        refresh_user_session()
        st.success('Order submitted successfully.')
        st.rerun()


def render_profile_page():
    st.title('Profile')
    user = get_current_user()
    outstanding = get_orders_for_user(user['id'], ACTIVE_ORDER_STATUSES)
    fulfilled = get_orders_for_user(user['id'], COMPLETED_ORDER_STATUSES)

    c1, c2, c3 = st.columns(3)
    c1.metric('Total balance owed', currency(float(user['balance_owed'])))
    c2.metric('Outstanding orders', len(outstanding))
    c3.metric('Fulfilled orders', len(fulfilled))

    st.write(f"**Name:** {user['first_name']} {user['last_name']}")
    st.write(f"**Email:** {user['email']}")

    saved_card = st.text_input('Saved card placeholder', value=user.get('saved_card', ''))
    if st.button('Update saved card placeholder'):
        update_saved_card(user['id'], saved_card)
        refresh_user_session()
        st.success('Saved card field updated.')
        st.rerun()

    st.divider()
    st.subheader('Change password')
    with st.form('change_password_form'):
        current_password = st.text_input('Current password', type='password')
        new_password = st.text_input(
            'New password', type='password',
            help=f'At least {MIN_PASSWORD_LENGTH} characters.',
        )
        confirm = st.text_input('Confirm new password', type='password')

        if st.form_submit_button('Update password', type='primary'):
            ok, error = change_password(
                user['email'], current_password, new_password, confirm
            )
            if ok:
                st.success('Password updated.')
            else:
                st.error(error)


ORDER_TABLE_COLUMNS = [
    'timestamp', 'product_name', 'sku', 'option_value',
    'quantity', 'total_price', 'status', 'note',
]

ORDER_COLUMN_CONFIG = {
    'timestamp': st.column_config.DatetimeColumn('Ordered', format='MMM D, YYYY h:mm a'),
    'product_name': st.column_config.TextColumn('Product', width='large'),
    'sku': st.column_config.TextColumn('SKU', width='small'),
    'option_value': st.column_config.TextColumn('Option', width='small'),
    'quantity': st.column_config.NumberColumn('Qty', width='small'),
    'total_price': st.column_config.NumberColumn('Total', format='$%.2f'),
    'status': st.column_config.TextColumn('Status', width='small'),
    'note': st.column_config.TextColumn('Note', width='medium'),
}


def _orders_dataframe(rows):
    if not rows:
        return pd.DataFrame(columns=ORDER_TABLE_COLUMNS)
    return pd.DataFrame([{k: row[k] for k in row.keys()} for row in rows])


def _render_orders_table(rows):
    df = _orders_dataframe(rows)[ORDER_TABLE_COLUMNS].copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=ORDER_COLUMN_CONFIG,
    )


def render_outstanding_orders_page():
    st.title('Outstanding Orders')
    user = get_current_user()
    rows = get_orders_for_user(user['id'], ACTIVE_ORDER_STATUSES)
    if not rows:
        st.info('No active orders right now.')
        return

    outstanding_total = sum(float(row['total_price'] or 0) for row in rows)
    c1, c2 = st.columns(2)
    c1.metric('Active orders', len(rows))
    c2.metric('Value of active orders', currency(outstanding_total))
    _render_orders_table(rows)


def render_order_history_page():
    st.title('Order History')
    user = get_current_user()
    rows = get_orders_for_user(user['id'])
    if not rows:
        st.info('No order history yet.')
        return

    st.caption(f'{len(rows)} order(s), all statuses.')
    _render_orders_table(rows)
    st.download_button(
        'Download my orders (CSV)',
        data=_orders_dataframe(rows)[ORDER_TABLE_COLUMNS].to_csv(index=False).encode('utf-8'),
        file_name='my_bowling_orders.csv',
        mime='text/csv',
    )


def render_security_notices(users):
    """
    Until a legacy account sets a password, anyone who knows its email address
    can claim it. Say so plainly rather than letting it sit unnoticed.
    """
    passwordless = [u for u in users if not str(u.get('password_hash') or '').strip()]

    if passwordless and not TEAM_ACCESS_CODE:
        names = ', '.join(str(u['email']) for u in passwordless[:5])
        more = f' and {len(passwordless) - 5} more' if len(passwordless) > 5 else ''
        st.error(
            f'**{len(passwordless)} account(s) have no password yet** ({names}{more}). '
            'Until each one sets a password, anyone who knows the email address can '
            'claim it. Set `TEAM_ACCESS_CODE` in `.streamlit/secrets.toml` to require '
            'a shared code, and ask everyone to set their password now.'
        )
    elif passwordless:
        st.warning(
            f'{len(passwordless)} account(s) have not set a password yet. They need '
            'the team access code to do so.'
        )


def render_owner_dashboard():
    st.title('Owner Dashboard')

    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        selected_statuses = st.multiselect(
            'Show orders with these statuses',
            ORDER_STATUS_OPTIONS,
            default=ORDER_STATUS_OPTIONS,
        )
    with filter_col2:
        bulk_status = st.selectbox('Bulk update filtered orders to', ORDER_STATUS_OPTIONS)

    # One connection, one round trip, instead of five separate helper calls.
    data = get_owner_dashboard_data(selected_statuses if selected_statuses else None)
    all_filtered_rows = data['orders']

    render_security_notices(data['users'])

    c1, c2 = st.columns(2)
    c1.metric('Pending bowling balls', data['pending_ball_count'])
    c2.metric('Pending orders', data['active_order_count'])

    st.subheader('Pending bowling ball summary')
    if data['grouped_balls']:
        grouped_df = pd.DataFrame([{k: row[k] for k in row.keys()} for row in data['grouped_balls']])
        st.dataframe(grouped_df, use_container_width=True)
    else:
        st.info('No bowling balls currently waiting to be ordered.')

    st.subheader('Order management')
    st.caption(f'{len(all_filtered_rows)} orders shown')

    if all_filtered_rows:
        if st.button('Apply bulk status to all shown orders', type='primary'):
            order_ids = [int(row['id']) for row in all_filtered_rows]
            update_all_orders_status(order_ids, bulk_status)
            st.success(f'Updated {len(order_ids)} orders to {bulk_status}.')
            st.rerun()
    else:
        st.info('No orders match the current filter.')

    for row in all_filtered_rows:
        with st.container(border=True):
            left, mid, right = st.columns([1, 2, 1])
            with left:
                show_image(row.get('image_url'), alt=str(row.get('product_name', '')))
            with mid:
                st.write(f"**{row['product_name']}**")
                st.write(f"Customer: {row['customer_first_name']} {row['customer_last_name']} ({row['customer_email']})")
                st.write(f"SKU: {row['sku'] or 'N/A'}")
                if row['option_type']:
                    st.write(f"{row['option_type']}: {row['option_value']}")
                st.write(f"Quantity: {row['quantity']}")
                st.write(f"Price: {currency(float(row['total_price']))}")
                st.write(f"Status: {row['status']}")
                st.write(f"Timestamp: {row['timestamp']}")
                if row['note']:
                    st.write(f"Note: {row['note']}")
                if str(row.get('product_url', '')).strip().startswith(('http://', 'https://')):
                    st.markdown(f"[Open Storm page]({row['product_url']})")
            with right:
                new_status = st.selectbox(
                    'Update status',
                    ORDER_STATUS_OPTIONS,
                    index=ORDER_STATUS_OPTIONS.index(row['status']) if row['status'] in ORDER_STATUS_OPTIONS else 0,
                    key=f"status_sel_{row['id']}"
                )
                if st.button('Apply status', key=f"apply_status_{row['id']}"):
                    update_order_status(row['id'], new_status)
                    st.success('Order status updated.')
                    st.rerun()
                if st.button('Delete order', key=f"delete_order_{row['id']}"):
                    st.session_state['delete_target_order_id'] = int(row['id'])
                    st.session_state['delete_target_product_name'] = str(row['product_name'])
                    st.rerun()

    if st.session_state.get('delete_target_order_id') is not None:
        confirm_delete_dialog(
            int(st.session_state['delete_target_order_id']),
            str(st.session_state.get('delete_target_product_name', 'this order')),
        )

    st.subheader('User balances')
    st.caption(
        'Reset password clears the account\'s password so the owner can set a new '
        'one from the "First time here?" tab. Orders and balance are untouched.'
    )
    for user in data['users']:
        cols = st.columns([2, 2, 1, 1, 1])
        cols[0].write(f"**{user['first_name']} {user['last_name']}**")
        has_password = bool(str(user.get('password_hash') or '').strip())
        cols[1].write(f"{user['email']}{'' if has_password else '  ⚠️ no password set'}")
        new_balance = cols[2].number_input(
            f"Balance {user['email']}", value=float(user['balance_owed']), step=1.0, key=f"bal_{user['id']}"
        )
        if cols[3].button('Save', key=f"save_bal_{user['id']}"):
            update_balance(user['id'], new_balance)
            st.success('Balance updated.')
            st.rerun()
        if cols[4].button('Reset password', key=f"reset_pw_{user['id']}", disabled=not has_password):
            clear_user_password(int(user['id']))
            st.success(f"Password cleared for {user['email']}.")
            st.rerun()

    export_df = _orders_dataframe(all_filtered_rows)
    csv_bytes = export_df.to_csv(index=False).encode('utf-8') if not export_df.empty else b''
    st.download_button('Export shown orders to CSV', data=csv_bytes, file_name='orders_export.csv', mime='text/csv')

    if st.button('Re-check bowling ball batch notification'):
        evaluate_ball_batch_notification()
        st.success('Batch notification logic re-run.')


def render_main_app():
    page = render_sidebar()
    if page == 'Catalog':
        render_catalog_page()
    elif page == 'Cart':
        render_cart_page()
    elif page == 'Checkout':
        render_checkout_page()
    elif page == 'Profile':
        render_profile_page()
    elif page == 'Outstanding Orders':
        render_outstanding_orders_page()
    elif page == 'Order History':
        render_order_history_page()
    elif page == 'Owner Dashboard' and is_admin():
        render_owner_dashboard()
    elif page == 'Catalog Manager' and is_admin():
        user = get_current_user() or {}
        render_catalog_manager(str(user.get('email', '')))


st.markdown(CATALOG_CSS, unsafe_allow_html=True)

if not is_logged_in():
    render_auth_page()
else:
    bootstrap_catalog_from_csv()
    render_main_app()
