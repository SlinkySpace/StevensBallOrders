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
CATALOG_COLUMNS = 4
CATALOG_ITEMS_PER_PAGE = 24  # a multiple of CATALOG_COLUMNS, so rows stay full
PLACEHOLDER_IMAGE = (
    "<div class='product-image product-image--empty'>No image</div>"
)

# Streamlit 1.55 publishes no theme CSS variables - the only custom property on
# the page is --overlay-top - so a rule written as var(--text-color, #16181D)
# silently uses the fallback forever, and looks wrong for anyone on dark.
#
# The theme is known on the server instead: st.context.theme reports which one
# this session is using, and the palettes below mirror .streamlit/config.toml.
# They are published as our own variables, which the stylesheet can then rely
# on. Keep these in step with config.toml if the theme there changes.
THEME_PALETTES = {
    'light': {'text': '#16181D', 'border': '#E3E5EA'},
    'dark': {'text': '#ECEDEF', 'border': '#2E323A'},
}


def theme_variables() -> str:
    """A :root block carrying the active theme's colours."""
    try:
        active = str(getattr(st.context.theme, 'type', '') or '').lower()
    except Exception:
        active = ''
    palette = THEME_PALETTES.get(active, THEME_PALETTES['light'])
    primary = st.get_option('theme.primaryColor') or '#A32638'
    return (
        "<style>:root{"
        f"--app-text:{palette['text']};"
        f"--app-border:{palette['border']};"
        f"--app-primary:{primary};"
        "}</style>"
    )


# From the Claude Design pass on the catalog grid, extended to the rest of the
# app. Two things carried over from before, deliberately: the square image and
# the two-line clamp on the name are what make tiles in a row match height,
# without any flexbox aimed at Streamlit's generated class names.
#
# Neutrals stay translucent grey so they read on either theme without knowing
# which one is active; anything that needs a real colour uses the variables
# above.
APP_CSS = """
<style>
.product-image {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: contain;
    border-radius: 0.5rem;
    padding: 0.375rem;
    box-sizing: border-box;
    background: rgba(128, 128, 128, 0.05);
    border: 1px solid rgba(128, 128, 128, 0.12);
}
.product-image--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(128, 128, 128, 0.65);
    font-size: 0.78rem;
}
.product-name {
    font-weight: 600;
    font-size: 0.9375rem;
    line-height: 1.3;
    letter-spacing: -0.005em;
    margin: 0.7rem 0 0.5rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.6em;
}
/* Price and SKU share a baseline, so the eye reads price first and the SKU
   sits back as reference rather than competing with it. */
.product-line {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.6rem;
}
.product-price {
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
}
.product-sku {
    font-family: 'Source Code Pro', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.6875rem;
    letter-spacing: 0.04em;
    opacity: 0.55;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 45%;
}
/* Tint the popover trigger towards the accent so "Add to cart" reads as the
   action on the card. */
[data-testid="stPopover"] button {
    border-color: color-mix(in srgb, var(--app-primary) 28%, transparent);
    background: color-mix(in srgb, var(--app-primary) 5%, transparent);
}
[data-testid="stPopover"] button:hover {
    border-color: var(--app-primary);
    background: color-mix(in srgb, var(--app-primary) 11%, transparent);
}

/* ---- shared across pages ---------------------------------------------- */

/* One page header treatment everywhere, so Cart and Order History announce
   themselves the same way the Catalog does. */
.page-head {
    font-size: 1.85rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.15;
    margin: 0 0 0.15rem;
}
.page-sub {
    font-size: 0.875rem;
    opacity: 0.62;
    margin: 0 0 1.15rem;
}

/* Order status, as a pill rather than a bare word. Each status keeps its own
   hue at a fixed low alpha, which stays legible on both themes - a solid fill
   would need a different colour per theme to keep its contrast. */
.status-pill {
    display: inline-block;
    padding: 0.16rem 0.6rem;
    border-radius: 999px;
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
    border: 1px solid;
}
/* Each status keeps its hue, but the text colour is mixed towards the theme's
   own text colour: near-black on light, near-white on dark. One declaration
   then stays readable on both, and it follows the theme Streamlit actually
   gave this session rather than the reader's OS preference, which are not
   always the same thing. */
.status-submitted {
    color: color-mix(in srgb, #D69E2E 58%, var(--app-text));
    background: rgba(214, 158, 46, 0.13);
    border-color: rgba(214, 158, 46, 0.35);
}
.status-approved {
    color: color-mix(in srgb, #4299E1 58%, var(--app-text));
    background: rgba(66, 153, 225, 0.13);
    border-color: rgba(66, 153, 225, 0.35);
}
.status-ordered {
    color: color-mix(in srgb, #805AD5 58%, var(--app-text));
    background: rgba(128, 90, 213, 0.13);
    border-color: rgba(128, 90, 213, 0.35);
}
.status-fulfilled {
    color: color-mix(in srgb, #48BB78 58%, var(--app-text));
    background: rgba(72, 187, 120, 0.14);
    border-color: rgba(72, 187, 120, 0.36);
}
.status-cancelled {
    color: color-mix(in srgb, #E53E3E 55%, var(--app-text));
    background: rgba(197, 48, 48, 0.11);
    border-color: rgba(197, 48, 48, 0.30);
}

/* Summary row above an order list: the same tabular figures as a product
   price, so money reads consistently wherever it appears. */
.summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 2.25rem;
    padding: 0.9rem 1.1rem;
    margin-bottom: 1rem;
    border: 1px solid rgba(128, 128, 128, 0.16);
    border-radius: 0.6rem;
    background: rgba(128, 128, 128, 0.04);
}
.summary-label {
    font-size: 0.6875rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    opacity: 0.6;
    margin-bottom: 0.2rem;
}
.summary-value {
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
}
.summary-value--accent { color: var(--app-primary); }

/* The header line of one order. Sits above a collapsed item table, so it
   carries everything worth scanning: who, when, how much, what state. */
.order-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.45rem 0.8rem;
    margin-bottom: 0.15rem;
}
.order-id {
    font-weight: 700;
    font-size: 1.02rem;
    letter-spacing: -0.01em;
}
.order-total {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    margin-left: auto;
    font-size: 1.05rem;
}
.order-meta {
    font-size: 0.8125rem;
    opacity: 0.6;
}
.order-customer {
    font-weight: 600;
    font-size: 0.8125rem;
    opacity: 0.85;
}

/* An empty cart or an empty history is a normal state, not a warning, and
   st.info's blue bar reads as though something needs attention. */
.empty-state {
    text-align: center;
    padding: 3rem 1.5rem;
    border: 1px dashed rgba(128, 128, 128, 0.28);
    border-radius: 0.75rem;
    background: rgba(128, 128, 128, 0.03);
}
/* A cart line names the product once, at full length - unlike a catalog tile,
   which clamps to two lines to keep a row of tiles the same height. */
.cart-item-name {
    font-weight: 650;
    font-size: 1.05rem;
    letter-spacing: -0.01em;
    margin-bottom: 0.3rem;
}
.cart-item-meta {
    font-size: 0.8125rem;
    opacity: 0.62;
    margin-bottom: 0.65rem;
}
.cart-line-total {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 0.7rem;
    padding-top: 0.6rem;
    border-top: 1px solid rgba(128, 128, 128, 0.16);
    font-size: 0.8125rem;
    opacity: 0.75;
}
.cart-line-total span {
    font-size: 1.1rem;
    font-weight: 700;
    opacity: 1;
    font-variant-numeric: tabular-nums;
}

/* Sign-in: the one page seen while logged out, so it carries the brand
   rather than opening on a bare form. */
.auth-brand {
    text-align: center;
    margin: 1.5rem 0 0.35rem;
}
.auth-brand__mark { font-size: 2.6rem; line-height: 1; }
.auth-brand__title {
    font-size: 1.7rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-top: 0.4rem;
}
.auth-brand__sub {
    font-size: 0.875rem;
    opacity: 0.6;
    margin: 0.3rem 0 1.4rem;
}

.empty-state__icon { font-size: 2rem; line-height: 1; margin-bottom: 0.6rem; }
.empty-state__title { font-weight: 650; font-size: 1.05rem; margin-bottom: 0.25rem; }
.empty-state__body { font-size: 0.875rem; opacity: 0.62; }
</style>
"""

# The pill only ever renders a status that has a matching CSS class; anything
# unrecognised falls back to the neutral 'submitted' look rather than showing
# up unstyled.
STATUS_PILL_CLASSES = {
    'submitted': 'status-submitted',
    'approved': 'status-approved',
    'ordered': 'status-ordered',
    'fulfilled': 'status-fulfilled',
    'cancelled': 'status-cancelled',
}


def page_header(title: str, subtitle: str = '') -> None:
    """Replaces st.title, so every page announces itself the same way."""
    markup = f"<div class='page-head'>{html.escape(title)}</div>"
    if subtitle:
        markup += f"<div class='page-sub'>{html.escape(subtitle)}</div>"
    st.markdown(markup, unsafe_allow_html=True)


def status_pill(status: str) -> str:
    """HTML for one status pill. Returns markup, so callers can inline it."""
    key = str(status or '').strip().lower()
    css = STATUS_PILL_CLASSES.get(key, 'status-submitted')
    return f"<span class='status-pill {css}'>{html.escape(key or 'unknown')}</span>"


def summary_row(figures: list[tuple[str, str]], accent_last: bool = True) -> None:
    """
    A row of labelled figures. Used instead of st.metric where the numbers are
    a summary of what is below rather than something that moves - st.metric's
    delta affordance implies a change that never comes.
    """
    cells = []
    for index, (label, value) in enumerate(figures):
        accent = ' summary-value--accent' if accent_last and index == len(figures) - 1 else ''
        cells.append(
            f"<div><div class='summary-label'>{html.escape(label)}</div>"
            f"<div class='summary-value{accent}'>{html.escape(value)}</div></div>"
        )
    st.markdown(f"<div class='summary-row'>{''.join(cells)}</div>", unsafe_allow_html=True)


def empty_state(icon: str, title: str, body: str = '') -> None:
    st.markdown(
        f"<div class='empty-state'><div class='empty-state__icon'>{icon}</div>"
        f"<div class='empty-state__title'>{html.escape(title)}</div>"
        + (f"<div class='empty-state__body'>{html.escape(body)}</div>" if body else '')
        + "</div>",
        unsafe_allow_html=True,
    )


def currency(value: float) -> str:
    return f"${value:,.2f}"


@st.cache_data(ttl=300, show_spinner=False)
def _static_image_files() -> set[str]:
    """
    Every file under static/, as posix paths relative to the app root.

    Used to tell a broken image path from a good one without stat()-ing the
    filesystem once per product card per rerun.

    The TTL matters: a catalog refresh adds image files while the app is
    running, and a permanently cached listing would keep reporting them as
    missing - the product would show "No image" even though the file is there.
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
    # Constrained to the middle third: a full-width login form on a wide screen
    # stretches its inputs across the whole monitor.
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        _render_auth_forms()


def _render_auth_forms():
    st.markdown(
        f"<div class='auth-brand'>"
        f"<div class='auth-brand__mark'>🎳</div>"
        f"<div class='auth-brand__title'>{html.escape(APP_TITLE)}</div>"
        f"</div>"
        f"<div class='auth-brand__sub' style='text-align:center'>"
        f"Team ordering at sponsor prices.</div>",
        unsafe_allow_html=True,
    )

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

        sku = str(row.get('sku') or '').strip()
        st.markdown(
            f"<div class='product-name' title=\"{html.escape(name, quote=True)}\">"
            f"{html.escape(name)}</div>"
            f"<div class='product-line'>"
            f"<span class='product-price'>{currency(price)}</span>"
            f"<span class='product-sku' title=\"{html.escape(sku, quote=True)}\">"
            f"{html.escape(sku)}</span>"
            f"</div>",
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
                    'sku': str(row.get('sku', '')),
                    'unit_price': price,
                    'image_url': str(row.get('image_url', '')),
                    'product_url': str(row.get('product_url', '')),
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
    page_header('Catalog', 'Storm equipment at team sponsor pricing.')
    df = load_catalog()

    if df.empty:
        empty_state(
            '🎳', 'The catalog is empty',
            'Load it from the Catalog Manager page.' if is_admin()
            else 'Ask an admin to run a catalog refresh.',
        )
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
    page_header('Cart', 'Adjust quantities and options before checking out.')
    ensure_cart()
    if not st.session_state['cart']:
        empty_state('🛒', 'Your cart is empty',
                    'Add something from the Catalog and it will show up here.')
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
                meta = [f"SKU {item['sku'] or 'N/A'}"]
                scent = str(item.get('scent', '') or '').strip()
                if item.get('product_type') == 'bowling_ball' and scent and scent.lower() != 'none':
                    meta.append(f"Scent: {scent}")
                meta.append(f"{currency(item['unit_price'])} each")

                st.markdown(
                    f"<div class='cart-item-name'>{html.escape(str(item['name']))}</div>"
                    f"<div class='cart-item-meta'>"
                    f"{html.escape('  ·  '.join(meta))}</div>",
                    unsafe_allow_html=True,
                )

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
                st.markdown(
                    f"<div class='cart-line-total'>Line total "
                    f"<span>{html.escape(currency(line_total))}</span></div>",
                    unsafe_allow_html=True,
                )

    if remove_index is not None:
        remove_cart_index(remove_index)
        st.rerun()

    if cart_changed:
        persist_cart()

    st.divider()
    left, right = st.columns([2, 1])
    with left:
        units = sum(int(i.get('quantity', 1)) for i in st.session_state['cart'])
        summary_row([
            ('Items', str(units)),
            ('Cart total', currency(total)),
        ])
    with right:
        if st.button('Empty cart', use_container_width=True):
            st.session_state['cart'] = []
            persist_cart()
            st.toast('Cart emptied.')
            st.rerun()


def render_checkout_page():
    page_header('Checkout', 'One order, containing everything below.')
    ensure_cart()
    if not st.session_state['cart']:
        empty_state('✅', 'Nothing to check out',
                    'Add items to your cart first.')
        return

    total = sum(float(item['unit_price']) * int(item['quantity']) for item in st.session_state['cart'])
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
    units = sum(int(i.get('quantity', 1)) for i in st.session_state['cart'])
    summary_row([
        ('Lines', str(len(st.session_state['cart']))),
        ('Items', str(units)),
        ('Estimated total', currency(total)),
    ])
    checkout_note = st.text_area('Checkout note (optional)')

    if st.button('Confirm and place order', type='primary'):
        user = get_current_user()
        place_order_items(user, st.session_state['cart'], checkout_note)
        st.session_state['cart'] = []
        refresh_user_session()
        st.success('Order submitted successfully.')
        st.rerun()


def render_profile_page():
    user = get_current_user()
    page_header(
        f"{user['first_name']} {user['last_name']}",
        str(user['email']),
    )
    outstanding = get_orders_for_user(user['id'], ACTIVE_ORDER_STATUSES)
    fulfilled = get_orders_for_user(user['id'], COMPLETED_ORDER_STATUSES)

    summary_row([
        ('Outstanding orders', str(len(outstanding))),
        ('Fulfilled orders', str(len(fulfilled))),
        ('Balance owed', currency(float(user['balance_owed']))),
    ])

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


ITEM_TABLE_COLUMNS = ['product_name', 'sku', 'option_value', 'quantity', 'unit_price', 'total_price', 'note']

ITEM_COLUMN_CONFIG = {
    'product_name': st.column_config.TextColumn('Product', width='large'),
    'sku': st.column_config.TextColumn('SKU', width='small'),
    'option_value': st.column_config.TextColumn('Option', width='small'),
    'quantity': st.column_config.NumberColumn('Qty', width='small'),
    'unit_price': st.column_config.NumberColumn('Unit', format='$%.2f'),
    'total_price': st.column_config.NumberColumn('Line total', format='$%.2f'),
    'note': st.column_config.TextColumn('Note', width='medium'),
}


def _items_dataframe(items):
    if not items:
        return pd.DataFrame(columns=ITEM_TABLE_COLUMNS)
    return pd.DataFrame(items).reindex(columns=ITEM_TABLE_COLUMNS)


def _flat_order_rows(orders):
    """One row per item, with its order's details alongside - for CSV export."""
    rows = []
    for order in orders:
        for item in order.get('items', []):
            rows.append({
                'order_id': order['id'],
                'ordered': order['timestamp'],
                'status': order['status'],
                'product_name': item.get('product_name', ''),
                'sku': item.get('sku', ''),
                'option_value': item.get('option_value', ''),
                'quantity': item.get('quantity', 0),
                'unit_price': item.get('unit_price', 0),
                'line_total': item.get('total_price', 0),
                'item_note': item.get('note', ''),
                'order_note': order.get('note', ''),
                'order_total': order.get('total_price', 0),
            })
    return rows


def _render_order_list(orders, show_customer: bool = False):
    """
    One card per order: a summary line that can be scanned down the page, with
    the items themselves folded away behind it.

    The summary is drawn as HTML rather than put in the expander's label
    because a label is plain text - it cannot carry the status pill, which is
    the thing worth seeing without opening anything.
    """
    for order in orders:
        items = order.get('items', [])
        unit_count = order.get('item_count', 0)
        plural = 's' if unit_count != 1 else ''

        with st.container(border=True):
            customer = ''
            if show_customer:
                customer = (
                    f"<span class='order-customer'>"
                    f"{html.escape(str(order['customer_first_name']))} "
                    f"{html.escape(str(order['customer_last_name']))}</span>"
                )

            st.markdown(
                f"<div class='order-head'>"
                f"<span class='order-id'>Order #{html.escape(str(order['id']))}</span>"
                f"{status_pill(order['status'])}"
                f"{customer}"
                f"<span class='order-total'>"
                f"{html.escape(currency(float(order['total_price'] or 0)))}</span>"
                f"</div>"
                f"<div class='order-meta'>{html.escape(str(order['timestamp']))}"
                f" &middot; {unit_count} item{plural}</div>",
                unsafe_allow_html=True,
            )

            if order.get('note'):
                st.caption(f"Note: {order['note']}")

            with st.expander(f"{len(items)} line{'s' if len(items) != 1 else ''}"):
                st.dataframe(
                    _items_dataframe(items),
                    use_container_width=True,
                    hide_index=True,
                    column_config=ITEM_COLUMN_CONFIG,
                )


def render_outstanding_orders_page():
    page_header('Outstanding Orders', 'Placed but not yet fulfilled.')
    user = get_current_user()
    orders = get_orders_for_user(user['id'], ACTIVE_ORDER_STATUSES)
    if not orders:
        empty_state('📦', 'Nothing outstanding',
                    'Orders you place will show here until they are fulfilled.')
        return

    outstanding_total = sum(float(o['total_price'] or 0) for o in orders)
    items_total = sum(o.get('item_count', 0) for o in orders)
    summary_row([
        ('Active orders', str(len(orders))),
        ('Items', str(items_total)),
        ('Value', currency(outstanding_total)),
    ])
    _render_order_list(orders)


def render_order_history_page():
    page_header('Order History', 'Every order you have placed, in any state.')
    user = get_current_user()
    orders = get_orders_for_user(user['id'])
    if not orders:
        empty_state('🕘', 'No orders yet',
                    'Once you check out, your orders appear here.')
        return

    spent = sum(float(o['total_price'] or 0) for o in orders
                if str(o['status']).lower() != 'cancelled')
    summary_row([
        ('Orders', str(len(orders))),
        ('Items', str(sum(o.get('item_count', 0) for o in orders))),
        ('Total ordered', currency(spent)),
    ])
    _render_order_list(orders)

    flat = _flat_order_rows(orders)
    if flat:
        st.download_button(
            'Download my orders (CSV)',
            data=pd.DataFrame(flat).to_csv(index=False).encode('utf-8'),
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
    page_header('Owner Dashboard', 'Everyone’s orders, and what still has to be placed.')

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

    summary_row([
        ('Pending bowling balls', str(data['pending_ball_count'])),
        ('Pending orders', str(data['active_order_count'])),
    ])

    st.subheader('Pending bowling ball summary')
    if data['grouped_balls']:
        grouped_df = pd.DataFrame([{k: row[k] for k in row.keys()} for row in data['grouped_balls']])
        st.dataframe(grouped_df, use_container_width=True)
    else:
        st.caption('No bowling balls currently waiting to be ordered.')

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

    for order in all_filtered_rows:
        items = order.get('items', [])
        unit_count = order.get('item_count', 0)

        with st.container(border=True):
            left, right = st.columns([3, 1])
            with left:
                st.markdown(
                    f"<div class='order-head'>"
                    f"<span class='order-id'>Order #{html.escape(str(order['id']))}</span>"
                    f"{status_pill(order['status'])}"
                    f"<span class='order-customer'>"
                    f"{html.escape(str(order['customer_first_name']))} "
                    f"{html.escape(str(order['customer_last_name']))}"
                    f" &middot; {html.escape(str(order['customer_email']))}</span>"
                    f"<span class='order-total'>"
                    f"{html.escape(currency(float(order['total_price'] or 0)))}</span>"
                    f"</div>"
                    f"<div class='order-meta'>{html.escape(str(order['timestamp']))}"
                    f" &middot; {unit_count} item{'s' if unit_count != 1 else ''}</div>",
                    unsafe_allow_html=True,
                )
                if order.get('note'):
                    st.caption(f"Note: {order['note']}")

                st.dataframe(
                    _items_dataframe(items),
                    use_container_width=True,
                    hide_index=True,
                    column_config=ITEM_COLUMN_CONFIG,
                )
            with right:
                # One control for the whole order, and one email when it changes.
                new_status = st.selectbox(
                    'Update status',
                    ORDER_STATUS_OPTIONS,
                    index=ORDER_STATUS_OPTIONS.index(order['status'])
                    if order['status'] in ORDER_STATUS_OPTIONS else 0,
                    key=f"status_sel_{order['id']}",
                )
                if st.button('Apply status', key=f"apply_status_{order['id']}",
                             use_container_width=True):
                    update_order_status(order['id'], new_status)
                    st.success('Order status updated.')
                    st.rerun()
                if st.button('Delete order', key=f"delete_order_{order['id']}",
                             use_container_width=True):
                    st.session_state['delete_target_order_id'] = int(order['id'])
                    st.session_state['delete_target_product_name'] = (
                        f"{unit_count} item{'s' if unit_count != 1 else ''}"
                    )
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

    # Flattened to one row per item, which is what you want when actually
    # placing the order with Storm.
    flat = _flat_order_rows(all_filtered_rows)
    csv_bytes = pd.DataFrame(flat).to_csv(index=False).encode('utf-8') if flat else b''
    st.download_button('Export shown orders to CSV', data=csv_bytes,
                       file_name='orders_export.csv', mime='text/csv')

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


st.markdown(theme_variables(), unsafe_allow_html=True)
st.markdown(APP_CSS, unsafe_allow_html=True)

if not is_logged_in():
    render_auth_page()
else:
    bootstrap_catalog_from_csv()
    render_main_app()
