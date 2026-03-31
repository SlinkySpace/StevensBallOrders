import pandas as pd
import streamlit as st

from auth import (
    get_current_user,
    init_session_state,
    is_admin,
    is_logged_in,
    login_user,
    logout_user,
    refresh_user_session,
    signup_user,
)
from catalog import filter_catalog, get_filter_options, get_option_config, load_catalog
from config import APP_TITLE, ACTIVE_ORDER_STATUSES, COMPLETED_ORDER_STATUSES
from db import (
    delete_order,
    evaluate_ball_batch_notification,
    get_all_orders,
    get_all_users,
    get_grouped_pending_ball_orders,
    get_orders_for_user,
    get_pending_ball_orders_count,
    init_db,
    place_order_items,
    update_all_orders_status,
    update_balance,
    update_order_status,
    update_saved_card,
)

st.set_page_config(page_title=APP_TITLE, layout='wide')
init_db()
init_session_state()
refresh_user_session()

ORDER_STATUS_OPTIONS = ['submitted', 'approved', 'ordered', 'fulfilled', 'cancelled']
CATALOG_ITEMS_PER_PAGE = 25


def currency(value: float) -> str:
    return f"${value:,.2f}"


@st.cache_data(show_spinner=False)
def get_catalog_df():
    return load_catalog()


def ensure_cart():
    if 'cart' not in st.session_state or st.session_state['cart'] is None:
        st.session_state['cart'] = []


def add_to_cart(item: dict):
    ensure_cart()
    st.session_state['cart'].append(item)


def remove_cart_index(index: int):
    ensure_cart()
    st.session_state['cart'].pop(index)


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
    left, right = st.columns(2)

    with left:
        st.subheader('Login')
        with st.form('login_form'):
            email = st.text_input('Email').strip().lower()
            submitted = st.form_submit_button('Login')
            if submitted:
                if login_user(email):
                    st.success('Logged in successfully.')
                    st.rerun()
                else:
                    st.error('No account found for that email.')

    with right:
        st.subheader('Create account')
        with st.form('signup_form'):
            first_name = st.text_input('First name')
            last_name = st.text_input('Last name')
            email = st.text_input('Email address').strip().lower()
            submitted = st.form_submit_button('Create account')
            if submitted:
                if not first_name or not last_name or not email:
                    st.error('Please complete all fields.')
                elif signup_user(first_name, last_name, email):
                    st.success('Account created.')
                    st.rerun()
                else:
                    st.error('An account with that email already exists.')



def render_sidebar():
    user = get_current_user()
    st.sidebar.title('Navigation')
    st.sidebar.write(f"Logged in as **{user['first_name']} {user['last_name']}**")
    st.sidebar.write(user['email'])

    cart_count = sum(int(item.get('quantity', 1)) for item in st.session_state.get('cart', []))
    st.sidebar.metric('Cart items', cart_count)
    if st.sidebar.button('Logout'):
        logout_user()
        st.rerun()

    base_pages = ['Catalog', 'Cart', 'Checkout', 'Profile', 'Outstanding Orders', 'Order History']
    if is_admin():
        base_pages.append('Owner Dashboard')
    return st.sidebar.radio('Go to', base_pages)


def render_catalog_page():
    st.header('Product Dashboard')
    df = get_catalog_df()
    main_options, sub_options = get_filter_options(df)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        selected_main = st.selectbox('Main category', main_options)
    with c2:
        selected_sub = st.selectbox('Sub category', sub_options)
    with c3:
        search = st.text_input('Search by product name or SKU')

    filtered = filter_catalog(df, search, selected_main, selected_sub).reset_index(drop=True)

    total_items = len(filtered)
    total_pages = max(1, (total_items + CATALOG_ITEMS_PER_PAGE - 1) // CATALOG_ITEMS_PER_PAGE)
    current_page = ensure_catalog_page_valid(total_pages)

    top_left, top_right = st.columns([2, 1])
    with top_left:
        st.caption(f'{total_items} products shown')
    with top_right:
        page_number = st.number_input(
            'Catalog page',
            min_value=1,
            max_value=total_pages,
            value=current_page,
            step=1,
        )
        current_page = int(page_number)
        st.session_state['catalog_page_number'] = current_page

    start_idx = (current_page - 1) * CATALOG_ITEMS_PER_PAGE
    end_idx = start_idx + CATALOG_ITEMS_PER_PAGE
    page_df = filtered.iloc[start_idx:end_idx]

    if total_items > 0:
        st.caption(f'Showing products {start_idx + 1} to {min(end_idx, total_items)} of {total_items}')
    else:
        st.caption('Showing 0 products')

    for idx, row in page_df.iterrows():
        row_key = f"{idx}_{str(row.get('sku', '')).strip()}_{str(row.get('product_url', '')).strip()}"

        with st.container(border=True):
            left, right = st.columns([1, 2])
            with left:
                if row['image_url']:
                    st.image(row['image_url'], use_container_width=True)
            with right:
                st.subheader(str(row['name']))
                st.write(f"**Price:** {currency(float(row['price_value']))}")
                st.write(f"**SKU:** {str(row['sku']) or 'N/A'}")
                if str(row.get('product_url', '')).strip():
                    st.markdown(f"[Open Storm product page]({row['product_url']})")

                option_config = get_option_config(row['product_type'])
                option_value = ''
                if option_config['options']:
                    option_value = st.selectbox(
                        option_config['option_type'],
                        option_config['options'],
                        key=f"opt_{row_key}"
                    )

                quantity = st.number_input(
                    'Quantity',
                    min_value=1,
                    max_value=20,
                    value=1,
                    step=1,
                    key=f"qty_{row_key}"
                )
                note = st.text_input(
                    'Order note (optional)',
                    key=f"note_{row_key}"
                )

                if st.button('Add to cart', key=f"add_{row_key}"):
                    add_to_cart({
                        'name': str(row['name']),
                        'sku': str(row['sku']),
                        'unit_price': float(row['price_value']),
                        'image_url': str(row['image_url']),
                        'product_url': str(row['product_url']),
                        'option_type': option_config['option_type'],
                        'option_value': option_value,
                        'quantity': int(quantity),
                        'note': note,
                        'main_category': str(row['main_category']),
                        'sub_category': str(row['sub_category']),
                        'product_type': str(row['product_type']),
                    })
                    st.success('Added to cart.')

    nav_left, nav_center, nav_right = st.columns([1, 2, 1])
    with nav_left:
        if st.button('← Previous', disabled=current_page <= 1, key='catalog_prev_bottom'):
            new_page = max(1, current_page - 1)
            st.session_state['catalog_page_number'] = new_page
            st.rerun()
    with nav_center:
        st.markdown(f"<div style='text-align:center; padding-top:0.5rem;'>Page {current_page} of {total_pages}</div>", unsafe_allow_html=True)
    with nav_right:
        if st.button('Next →', disabled=current_page >= total_pages, key='catalog_next_bottom'):
            new_page = min(total_pages, current_page + 1)
            st.session_state['catalog_page_number'] = new_page
            st.rerun()


def render_cart_page():
    st.header('Cart')
    ensure_cart()
    if not st.session_state['cart']:
        st.info('Your cart is empty.')
        return

    total = 0.0
    remove_index = None
    for idx, item in enumerate(st.session_state['cart']):
        with st.container(border=True):
            left, right = st.columns([1, 2])
            with left:
                if item.get('image_url'):
                    st.image(item['image_url'], use_container_width=True)
            with right:
                st.write(f"**{item['name']}**")
                st.write(f"SKU: {item['sku'] or 'N/A'}")
                st.write(f"Unit price: {currency(item['unit_price'])}")

                qty = st.number_input(
                    f"Quantity #{idx+1}", min_value=1, max_value=20,
                    value=int(item.get('quantity', 1)), key=f"cart_qty_{idx}"
                )
                item['quantity'] = int(qty)

                if item.get('option_type'):
                    options = get_option_config(item.get('product_type', 'general'))['options']
                    current = item.get('option_value', options[0] if options else '')
                    if current not in options and options:
                        options = [current] + options
                    item['option_value'] = st.selectbox(
                        item['option_type'], options, index=options.index(current) if options else 0,
                        key=f"cart_opt_{idx}"
                    ) if options else current

                item['note'] = st.text_input('Item note', value=item.get('note', ''), key=f"cart_note_{idx}")
                if st.button('Remove item', key=f"remove_{idx}"):
                    remove_index = idx

                line_total = float(item['unit_price']) * int(item['quantity'])
                total += line_total
                st.write(f"**Line total:** {currency(line_total)}")

    if remove_index is not None:
        remove_cart_index(remove_index)
        st.rerun()

    st.metric('Cart total', currency(total))


def render_checkout_page():
    st.header('Checkout')
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
    st.header('Profile')
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


def _orders_dataframe(rows):
    if not rows:
        return pd.DataFrame(columns=['timestamp', 'product_name', 'sku', 'option_value', 'quantity', 'total_price', 'status', 'note'])
    return pd.DataFrame([{k: row[k] for k in row.keys()} for row in rows])


def render_outstanding_orders_page():
    st.header('Outstanding Orders')
    user = get_current_user()
    rows = get_orders_for_user(user['id'], ACTIVE_ORDER_STATUSES)
    if not rows:
        st.info('No active orders right now.')
        return
    df = _orders_dataframe(rows)[['timestamp', 'product_name', 'sku', 'option_value', 'quantity', 'total_price', 'status', 'note']]
    st.dataframe(df, use_container_width=True)


def render_order_history_page():
    st.header('Fulfilled Orders / History')
    user = get_current_user()
    rows = get_orders_for_user(user['id'])
    if not rows:
        st.info('No order history yet.')
        return
    df = _orders_dataframe(rows)[['timestamp', 'product_name', 'sku', 'option_value', 'quantity', 'total_price', 'status', 'note']]
    st.dataframe(df, use_container_width=True)


def render_owner_dashboard():
    st.header('Owner Dashboard')
    pending_ball_count = get_pending_ball_orders_count()
    grouped_balls = get_grouped_pending_ball_orders()

    c1, c2 = st.columns(2)
    c1.metric('Pending bowling balls', pending_ball_count)
    c2.metric('Pending orders', len(get_all_orders(['submitted', 'approved', 'ordered'])))

    st.subheader('Pending bowling ball summary')
    if grouped_balls:
        grouped_df = pd.DataFrame([{k: row[k] for k in row.keys()} for row in grouped_balls])
        st.dataframe(grouped_df, use_container_width=True)
    else:
        st.info('No bowling balls currently waiting to be ordered.')

    st.subheader('Order management')
    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        selected_statuses = st.multiselect(
            'Show orders with these statuses',
            ORDER_STATUS_OPTIONS,
            default=ORDER_STATUS_OPTIONS,
        )
    with filter_col2:
        bulk_status = st.selectbox('Bulk update filtered orders to', ORDER_STATUS_OPTIONS)

    all_filtered_rows = get_all_orders(selected_statuses if selected_statuses else None)
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
                if row['image_url']:
                    st.image(row['image_url'], use_container_width=True)
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
                if str(row.get('product_url', '')).strip():
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
    users = get_all_users()
    for user in users:
        cols = st.columns([2, 2, 1, 1])
        cols[0].write(f"**{user['first_name']} {user['last_name']}**")
        cols[1].write(user['email'])
        new_balance = cols[2].number_input(
            f"Balance {user['email']}", value=float(user['balance_owed']), step=1.0, key=f"bal_{user['id']}"
        )
        if cols[3].button('Save', key=f"save_bal_{user['id']}"):
            update_balance(user['id'], new_balance)
            st.success('Balance updated.')
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


if not is_logged_in():
    render_auth_page()
else:
    render_main_app()
