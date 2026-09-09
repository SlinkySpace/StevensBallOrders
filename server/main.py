"""
The write path, in Python.

Every write to the database goes through db.py, exactly as the Streamlit app
and sync_catalog.py do. That is the whole point of this service: there is one
implementation of upsert_products, place_order_items and the rest, so a second
front end cannot drift from it on the code that deletes rows and charges people.

A front end may read straight from Postgres if it likes - a wrong read renders
a wrong page, which is recoverable. A wrong write is not.

Run it:
    pip install -r api/requirements.txt
    SESSION_SECRET=... uvicorn server.main:app --reload --port 8000
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Import the app's modules from the repo root, so this service uses the same
# db.py the Streamlit app and the scraper use rather than a copy of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import auth  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import runtime  # noqa: E402

from server import sessions  # noqa: E402


ORDER_STATUSES = ('submitted', 'approved', 'ordered', 'fulfilled', 'cancelled')


def _write_block_reason() -> Optional[str]:
    """
    Why writes are refused, or None when they are allowed.

    Streamlit is still the live app. This service can write to the same
    database, so pointing it at production has to be a deliberate act rather
    than a side effect of deploying.

    Reported rather than raised. Raising at startup crashes the function, and a
    crashed serverless function looks exactly like a missing dependency - which
    is the bug this deployment already had once. Refusing per request instead
    keeps the reason visible at /api/health.
    """
    url = str(getattr(config, 'DATABASE_URL', '') or '')
    if not url:
        return None  # local SQLite, nothing to protect
    if os.environ.get('ALLOW_PRODUCTION_WRITES', '').lower() in {'1', 'true', 'yes'}:
        return None
    host = url.split('@')[-1].split('/')[0]
    return (
        f'Writes are disabled: DATABASE_URL points at {host}, the live database '
        'the Streamlit app serves, and ALLOW_PRODUCTION_WRITES is not set. '
        'Reads work. Set ALLOW_PRODUCTION_WRITES=1 when this service is meant '
        'to take orders.'
    )


def require_writable() -> None:
    reason = _write_block_reason()
    if reason:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reason)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Deliberately does not touch schema against a hosted database.

    db.init_db() creates tables and runs migrations. That is schema ownership,
    and this service is explicitly not the owner - the Streamlit app and
    sync_catalog.py are. Running it here also made every cold start depend on
    reaching Neon, so an unreachable database failed the whole function rather
    than one request.

    A blank DATABASE_URL means a local SQLite file, which genuinely has no
    schema until something makes one, so there it still runs.
    """
    if not str(getattr(config, 'DATABASE_URL', '') or ''):
        db.init_db()
    yield


app = FastAPI(title='Bowling order write API', version='0.1.0', lifespan=lifespan)

# During development the front end is on :3000 and this is on :8000, so the
# session cookie crosses origins. In production both sit behind one origin and
# this can go.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin for origin in
        os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(',')
        if origin
    ],
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH'],
    allow_headers=['Content-Type'],
)


def _public(user) -> dict:
    """A user without the password hash, which never leaves the server."""
    return {k: v for k, v in dict(user).items() if k != 'password_hash'}


# --- session plumbing ------------------------------------------------------

def current_user(session: Optional[str] = Cookie(default=None, alias=sessions.COOKIE_NAME)):
    """The signed-in user, re-read from the database on every request."""
    email = sessions.read(session)
    if not email:
        return None
    user = db.get_user_by_email(email)
    return _public(user) if user else None


def require_user(user=Depends(current_user)):
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Not signed in.')
    return user


def require_admin(user=Depends(require_user)):
    if not auth.is_owner_email(user.get('email', '')):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Owners only.')
    return user


def _set_session_cookie(response: Response, email: str) -> None:
    response.set_cookie(
        sessions.COOKIE_NAME,
        sessions.issue(email),
        max_age=sessions.MAX_AGE_SECONDS,
        httponly=True,   # JavaScript must not be able to read it
        samesite='lax',  # not sent on cross-site POSTs, which blunts CSRF
        secure=os.environ.get('COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'},
        path='/',
    )


# --- auth ------------------------------------------------------------------

class Credentials(BaseModel):
    email: str
    password: str


class Registration(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    confirm: str
    access_code: str = ''


class ClaimAccount(BaseModel):
    email: str
    password: str
    confirm: str
    access_code: str = ''


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
    confirm: str


@app.post('/api/auth/login')
def login(body: Credentials, response: Response):
    user, error = auth.authenticate(body.email, body.password)
    if user is None:
        # 401 with the same wording for every failure, so a caller cannot work
        # out which addresses have accounts.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, error)
    _set_session_cookie(response, str(user['email']))
    return {'user': _public(user)}


@app.post('/api/auth/signup')
def signup(body: Registration, response: Response, _writable=Depends(require_writable)):
    user, error = auth.register(body.first_name, body.last_name, body.email,
                                body.password, body.confirm, body.access_code)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    _set_session_cookie(response, str(user['email']))
    return {'user': _public(user)}


@app.post('/api/auth/claim')
def claim(body: ClaimAccount, response: Response, _writable=Depends(require_writable)):
    """Set a password on an account created before passwords existed."""
    user, error = auth.claim_account(body.email, body.password,
                                     body.confirm, body.access_code)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    _set_session_cookie(response, str(user['email']))
    return {'user': _public(user)}


@app.post('/api/auth/logout')
def logout(response: Response):
    response.delete_cookie(sessions.COOKIE_NAME, path='/')
    return {'ok': True}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return {
        'user': user,
        'is_admin': bool(user and auth.is_owner_email(user.get('email', ''))),
    }


@app.post('/api/auth/password')
def change_password(body: PasswordChange, user=Depends(require_user),
                    _writable=Depends(require_writable)):
    ok, error = auth.change_password(str(user['email']), body.current_password,
                                     body.new_password, body.confirm)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    return {'ok': True}


# --- cart ------------------------------------------------------------------

class CartLine(BaseModel):
    product_url: str
    name: str
    sku: str = ''
    unit_price: float = 0.0
    quantity: int = Field(default=1, ge=1, le=20)
    option_type: str = ''
    option_value: str = ''
    note: str = ''
    image_url: str = ''
    product_type: str = 'general'
    scent: str = ''


@app.get('/api/cart')
def read_cart(user=Depends(require_user)):
    return {'cart': db.get_saved_cart(int(user['id']))}


@app.put('/api/cart')
def write_cart(lines: list[CartLine], user=Depends(require_user),
               _writable=Depends(require_writable)):
    db.save_cart(int(user['id']), [line.model_dump() for line in lines])
    return {'ok': True, 'lines': len(lines)}


# --- orders ----------------------------------------------------------------

class Checkout(BaseModel):
    note: str = ''


@app.get('/api/orders')
def my_orders(user=Depends(require_user)):
    return {'orders': [dict(order) for order in db.get_orders_for_user(int(user['id']))]}


@app.post('/api/orders')
def place_order(body: Checkout, user=Depends(require_user),
                _writable=Depends(require_writable)):
    """
    Turn the saved cart into an order.

    The cart is read from the database rather than taken from the request body,
    so the price charged is the price the server holds. A client that posted its
    own line items could otherwise name its own prices.
    """
    cart = db.get_saved_cart(int(user['id']))
    if not cart:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Your cart is empty.')

    order_id = db.place_order_items(dict(user), cart, body.note)
    db.clear_saved_cart(int(user['id']))
    return {'ok': True, 'order_id': order_id}


class StatusChange(BaseModel):
    status: str


@app.get('/api/admin/orders')
def all_orders(_admin=Depends(require_admin)):
    return {'orders': [dict(order) for order in db.get_all_orders()]}


@app.patch('/api/admin/orders/{order_id}')
def set_order_status(order_id: int, body: StatusChange,
                     _admin=Depends(require_admin),
                     _writable=Depends(require_writable)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            'Unknown status. Expected one of ' + ', '.join(ORDER_STATUSES) + '.',
        )
    if not db.get_order(order_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'No such order.')
    db.update_order_status(order_id, body.status)
    return {'ok': True, 'order_id': order_id, 'status': body.status}


@app.get('/api/health')
def health():
    """Whether this deployment can read, and whether it may write."""
    blocked = _write_block_reason()
    return {
        'ok': True,
        'products': db.count_products(),
        'writes_enabled': blocked is None,
        'writes_blocked_because': blocked,
        'streamlit_installed': runtime.RUNNING_UNDER_STREAMLIT,
    }
