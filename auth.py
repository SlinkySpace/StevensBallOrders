"""
Login, signup and password handling.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library, stored
in Django's familiar `algorithm$iterations$salt$hash` format. Using stdlib means
no extra dependency to install on the host.
"""

import base64
import hashlib
import hmac
import secrets
import time

import streamlit as st

from config import MIN_PASSWORD_LENGTH, OWNER_EMAILS, TEAM_ACCESS_CODE
from db import (
    create_user,
    get_saved_cart,
    get_user_by_email,
    set_user_password,
)

PBKDF2_ALGORITHM = 'pbkdf2_sha256'
PBKDF2_ITERATIONS = 600_000  # OWASP's 2023 floor for PBKDF2-HMAC-SHA256
SALT_BYTES = 16

# Brute-force damping. Held in module state, which lives as long as the server
# process - enough to blunt online guessing without adding a table.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
_failed_logins: dict[str, tuple[int, float]] = {}

SESSION_DEFAULTS = {
    'user_email': None,
    'user': None,
    'cart': [],
}


# --------------------------------------------------------------------------
# Password primitives
# --------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return '$'.join([
        PBKDF2_ALGORITHM,
        str(PBKDF2_ITERATIONS),
        base64.b64encode(salt).decode('ascii'),
        base64.b64encode(digest).decode('ascii'),
    ])


def verify_password(password: str, stored: str) -> bool:
    stored = str(stored or '')
    if not stored or not password:
        return False

    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split('$')
        if algorithm != PBKDF2_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, int(iterations)
    )
    # Constant time, so a wrong password can't be narrowed down by timing.
    return hmac.compare_digest(candidate, expected)


def password_problem(password: str, confirm: str | None = None) -> str | None:
    """Return a human-readable reason the password is unacceptable, else None."""
    if not password:
        return 'Please enter a password.'
    if len(password) < MIN_PASSWORD_LENGTH:
        return f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'
    if password.strip() != password:
        return 'Password cannot start or end with a space.'
    if confirm is not None and password != confirm:
        return 'The two passwords do not match.'
    return None


def _access_code_problem(supplied: str) -> str | None:
    if not TEAM_ACCESS_CODE:
        return None
    if not hmac.compare_digest(str(supplied or '').strip(), TEAM_ACCESS_CODE):
        return 'That team access code is not correct.'
    return None


# --------------------------------------------------------------------------
# Lockout
# --------------------------------------------------------------------------

def lockout_seconds_remaining(email: str) -> int:
    key = str(email or '').strip().lower()
    attempts, first_seen = _failed_logins.get(key, (0, 0.0))
    if attempts < MAX_FAILED_ATTEMPTS:
        return 0

    elapsed = time.monotonic() - first_seen
    if elapsed >= LOCKOUT_SECONDS:
        _failed_logins.pop(key, None)
        return 0
    return int(LOCKOUT_SECONDS - elapsed) + 1


def _record_failure(email: str) -> None:
    key = str(email or '').strip().lower()
    attempts, first_seen = _failed_logins.get(key, (0, 0.0))
    if attempts == 0 or time.monotonic() - first_seen >= LOCKOUT_SECONDS:
        _failed_logins[key] = (1, time.monotonic())
    else:
        _failed_logins[key] = (attempts + 1, first_seen)


def _clear_failures(email: str) -> None:
    _failed_logins.pop(str(email or '').strip().lower(), None)


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------

def init_session_state():
    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _public_user(user) -> dict:
    """The user dict minus the password hash, which never enters session state."""
    return {k: v for k, v in dict(user).items() if k != 'password_hash'}


def _start_session(user) -> None:
    st.session_state['user_email'] = user['email']
    st.session_state['user'] = _public_user(user)
    st.session_state['cart'] = get_saved_cart(int(user['id']))


def refresh_user_session():
    email = st.session_state.get('user_email')
    if not email:
        st.session_state['user'] = None
        return
    user = get_user_by_email(email)
    st.session_state['user'] = _public_user(user) if user else None


def logout_user():
    st.session_state['user_email'] = None
    st.session_state['user'] = None
    st.session_state['cart'] = []


# --------------------------------------------------------------------------
# Login / signup
# --------------------------------------------------------------------------

def account_needs_password(email: str) -> bool:
    """True for accounts that predate passwords and haven't set one yet."""
    user = get_user_by_email(email)
    return bool(user) and not str(user.get('password_hash') or '').strip()


def login_user(email: str, password: str) -> tuple[bool, str]:
    email = str(email or '').strip().lower()
    if not email:
        return False, 'Please enter your email address.'

    locked = lockout_seconds_remaining(email)
    if locked:
        return False, f'Too many failed attempts. Try again in {locked} seconds.'

    user = get_user_by_email(email)
    if not user or not verify_password(password, user.get('password_hash')):
        _record_failure(email)
        # Deliberately identical for unknown emails and wrong passwords, so the
        # form can't be used to discover who has an account.
        return False, 'Incorrect email or password.'

    _clear_failures(email)
    _start_session(user)
    return True, ''


def set_initial_password(email: str, password: str, confirm: str,
                         access_code: str = '') -> tuple[bool, str]:
    """
    First-time password setup for an account created before passwords existed.
    Logs the user in on success.
    """
    email = str(email or '').strip().lower()

    locked = lockout_seconds_remaining(email)
    if locked:
        return False, f'Too many failed attempts. Try again in {locked} seconds.'

    user = get_user_by_email(email)
    if not user:
        return False, 'No account found for that email.'

    if str(user.get('password_hash') or '').strip():
        return False, 'That account already has a password. Please log in instead.'

    code_problem = _access_code_problem(access_code)
    if code_problem:
        _record_failure(email)
        return False, code_problem

    problem = password_problem(password, confirm)
    if problem:
        return False, problem

    set_user_password(int(user['id']), hash_password(password))
    _clear_failures(email)
    _start_session(get_user_by_email(email))
    return True, ''


def signup_user(first_name: str, last_name: str, email: str, password: str,
                confirm: str, access_code: str = '') -> tuple[bool, str]:
    first_name = str(first_name or '').strip()
    last_name = str(last_name or '').strip()
    email = str(email or '').strip().lower()

    if not first_name or not last_name or not email:
        return False, 'Please complete all fields.'
    if '@' not in email:
        return False, 'Please enter a valid email address.'

    code_problem = _access_code_problem(access_code)
    if code_problem:
        return False, code_problem

    problem = password_problem(password, confirm)
    if problem:
        return False, problem

    if not create_user(first_name, last_name, email, hash_password(password)):
        return False, 'An account with that email already exists.'

    _start_session(get_user_by_email(email))
    return True, ''


def change_password(email: str, current_password: str, new_password: str,
                    confirm: str) -> tuple[bool, str]:
    user = get_user_by_email(email)
    if not user:
        return False, 'Account not found.'

    if not verify_password(current_password, user.get('password_hash')):
        return False, 'Your current password is not correct.'

    problem = password_problem(new_password, confirm)
    if problem:
        return False, problem
    if verify_password(new_password, user.get('password_hash')):
        return False, 'That is already your current password.'

    set_user_password(int(user['id']), hash_password(new_password))
    return True, ''


def get_current_user():
    return st.session_state.get('user')


def is_logged_in() -> bool:
    return st.session_state.get('user') is not None


def is_admin() -> bool:
    user = get_current_user()
    owner_emails = {str(email).strip().lower() for email in OWNER_EMAILS if str(email).strip()}
    return bool(user and user.get('email', '').strip().lower() in owner_emails)
