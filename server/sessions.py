"""
Signed-cookie sessions, replacing what st.session_state did for free.

A session is the user's email plus an issue time, signed with HMAC-SHA256 and
handed to the browser as a cookie. Nothing is stored server-side, which is what
lets this run on serverless where there is no process to keep state in - the
same reason db.py's cached connection pool has to go.

The cookie carries no password, no hash and no balance, only an email and a
timestamp. Everything else is read from the database on each request, so a
stale cookie cannot carry stale money.
"""

import base64
import hashlib
import hmac
import json
import os
import time

COOKIE_NAME = 'bowling_session'
MAX_AGE_SECONDS = 14 * 24 * 60 * 60  # two weeks


def _secret() -> bytes:
    secret = os.environ.get('SESSION_SECRET', '')
    if not secret:
        raise RuntimeError(
            'SESSION_SECRET is not set. Generate one with:\n'
            "    python -c \"import secrets; print(secrets.token_urlsafe(48))\"\n"
            'Sessions are signed with it, so changing it logs everyone out.'
        )
    return secret.encode('utf-8')


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _b64decode(text: str) -> bytes:
    padding = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def issue(email: str) -> str:
    """Return a signed cookie value for this email."""
    payload = json.dumps(
        {'email': str(email).strip().lower(), 'iat': int(time.time())},
        separators=(',', ':'), sort_keys=True,
    ).encode('utf-8')
    body = _b64encode(payload)
    signature = hmac.new(_secret(), body.encode('ascii'), hashlib.sha256).digest()
    return f'{body}.{_b64encode(signature)}'


def read(cookie: str | None) -> str | None:
    """Return the email a cookie vouches for, or None if it does not."""
    if not cookie or '.' not in cookie:
        return None

    body, _, signature = cookie.partition('.')
    try:
        expected = hmac.new(_secret(), body.encode('ascii'), hashlib.sha256).digest()
        # Constant time: a forged signature must not be improvable by timing.
        if not hmac.compare_digest(expected, _b64decode(signature)):
            return None
        payload = json.loads(_b64decode(body))
    except Exception:
        return None

    issued = payload.get('iat')
    if not isinstance(issued, int) or time.time() - issued > MAX_AGE_SECONDS:
        return None

    email = payload.get('email')
    return email if isinstance(email, str) and email else None
