import streamlit as st

from config import OWNER_EMAILS
from db import create_user, get_saved_cart, get_user_by_email


SESSION_DEFAULTS = {
    'user_email': None,
    'user': None,
    'cart': [],
}


def init_session_state():
    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def login_user(email: str) -> bool:
    user = get_user_by_email(email)
    if not user:
        return False
    st.session_state['user_email'] = user['email']
    st.session_state['user'] = dict(user)
    st.session_state['cart'] = get_saved_cart(int(user['id']))
    return True


def refresh_user_session():
    email = st.session_state.get('user_email')
    if not email:
        st.session_state['user'] = None
        return
    user = get_user_by_email(email)
    st.session_state['user'] = dict(user) if user else None


def logout_user():
    st.session_state['user_email'] = None
    st.session_state['user'] = None
    st.session_state['cart'] = []


def signup_user(first_name: str, last_name: str, email: str):
    created = create_user(first_name, last_name, email)
    if created:
        login_user(email)
    return created


def get_current_user():
    return st.session_state.get('user')


def is_logged_in() -> bool:
    return st.session_state.get('user') is not None


def is_admin() -> bool:
    user = get_current_user()
    owner_emails = {str(email).strip().lower() for email in OWNER_EMAILS if str(email).strip()}
    return bool(user and user.get('email', '').strip().lower() in owner_emails)