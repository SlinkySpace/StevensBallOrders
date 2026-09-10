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

import mimetypes
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Import the app's modules from the repo root, so this service uses the same
# db.py the Streamlit app and the scraper use rather than a copy of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import auth  # noqa: E402
import catalog_rows  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import freshness  # noqa: E402
import runtime  # noqa: E402

from server import sessions  # noqa: E402


ORDER_STATUSES = ('submitted', 'approved', 'ordered', 'fulfilled', 'cancelled')


# postgres:// URIs carry the password in the netloc, and psycopg quotes the
# whole connection string back in several of its errors - a malformed one most
# of all, because it cannot tell a URI from a keyword/value string and echoes
# what it was given. /api/health is public and unauthenticated, so anything
# derived from an exception goes through here first.
_CREDENTIAL_PATTERNS = (
    re.compile(r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^:/@\s"\']+:[^@\s"\']*@'),
    re.compile(r'(?i)\bpassword\s*=\s*[^\s"\']+'),
)


def _redact(text: str) -> str:
    """Strip credentials out of an error message before it is returned."""
    out = str(text)
    secret = str(getattr(config, 'DATABASE_URL', '') or '')
    if secret:
        out = out.replace(secret, '[redacted DATABASE_URL]')
    out = _CREDENTIAL_PATTERNS[0].sub(lambda m: m.group('scheme') + '[redacted]@', out)
    out = _CREDENTIAL_PATTERNS[1].sub('password=[redacted]', out)
    return out


def _describe(exc: BaseException) -> str:
    return _redact(f'{type(exc).__name__}: {exc}')


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


_startup_error: Optional[str] = None


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
    schema until something makes one, so there it still runs - but only where
    something can be written. On serverless the deployment directory is
    read-only, so a missing DATABASE_URL sends init_db() at a file it cannot
    create, and raising here takes down every route with an opaque 500.

    So the failure is recorded instead of raised, for the same reason
    _write_block_reason() reports rather than raises: a crashed function looks
    identical to a missing dependency, and /api/health can only say what went
    wrong if it is still running to be asked.
    """
    global _startup_error
    if not str(getattr(config, 'DATABASE_URL', '') or ''):
        try:
            db.init_db()
        except Exception as exc:
            _startup_error = _describe(exc)
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


# The catalog images, served from the same origin as the data.
#
# They live in static/ at the repo root, which is where the refresh workflow
# commits them and where the scraper writes them. The frontend used to read
# that directory off the filesystem, which only works when both halves share a
# checkout - deployed as its own project rooted at web/, static/ is outside its
# root and every product renders without a picture.
#
# Serving them here instead means the frontend needs nothing but an API URL.
# Python's mimetypes table is built from the system's, and the slim image the
# function runs on does not know .webp - every catalog image went out as
# application/octet-stream. Browsers sniff an <img> back to an image anyway, so
# this was invisible, but nothing else that touches the bytes would.
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('image/avif', '.avif')


class _CachedStatic(StaticFiles):
    """Serve the catalog images as immutable.

    download_images.py names them <id>_<content hash>.webp, so a changed image
    is a changed URL and one of these can never go stale. The default is
    max-age=0, must-revalidate, which put a round trip on the wire for every
    one of the 24 images on a page of the catalog, every load.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers['cache-control'] = 'public, max-age=31536000, immutable'
        return response


_STATIC_DIR = Path(__file__).resolve().parents[1] / 'static'
if _STATIC_DIR.is_dir():
    app.mount('/static', _CachedStatic(directory=_STATIC_DIR), name='static')


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


# --- catalog ---------------------------------------------------------------

def _decorate(product) -> dict:
    row = dict(product)
    row.update(catalog_rows.get_option_config(str(row.get('product_type') or 'general')))
    return row


@app.get('/api/products')
def products(_user=Depends(require_user)):
    """
    The catalog a shopper sees, with each product's weight or size options
    resolved.

    Behind a session because these are the team's sponsor prices, which are not
    the public ones and are not ours to publish.

    Out of stock and unpriced products are left out rather than shown greyed:
    Storm drops the price from a product page when it cannot be ordered, so
    those two are the same 22 items today, and both rendered as a $0.00 card
    with a working Add to cart. The Catalog Manager still lists them, which is
    where a price gets fixed.
    """
    rows = [_decorate(p) for p in
            db.get_products(visible_only=True, in_stock_only=True, priced_only=True)]
    mains = sorted({r['main_category'] for r in rows if r['main_category']})
    subs = sorted({r['sub_category'] for r in rows if r['sub_category']})
    return {'products': rows, 'main_categories': mains, 'sub_categories': subs}


@app.get('/api/catalog/freshness')
def catalog_freshness(_user=Depends(require_user)):
    """
    How old the catalog is, in words.

    Storm's session cookies expire within the hour, so a refresh needs somebody
    present to run it. Nothing nags about that on its own, so the number is
    exposed for the frontend to show.
    """
    signals = db.get_catalog_freshness()
    stamp = (signals.get('last_import') or {}).get('at') or signals.get('last_product_change')
    age_text, age_days = freshness.humanize_age(stamp) if stamp else ('never', 10**6)
    return {**signals, 'age': age_text, 'age_days': age_days,
            'stale': freshness.is_stale(age_days),
            'stale_after_days': freshness.STALE_CATALOG_DAYS}


# --- profile ---------------------------------------------------------------

class SavedCard(BaseModel):
    saved_card: str = ''


@app.post('/api/profile/saved-card')
def set_saved_card(body: SavedCard, user=Depends(require_user),
                   _writable=Depends(require_writable)):
    db.update_saved_card(int(user['id']), body.saved_card)
    return {'ok': True}


# --- owner dashboard -------------------------------------------------------

@app.get('/api/admin/dashboard')
def admin_dashboard(statuses: str = '', _admin=Depends(require_admin)):
    wanted = [s for s in statuses.split(',') if s in ORDER_STATUSES] or None
    data = db.get_owner_dashboard_data(wanted)
    users = []
    for row in data['users']:
        row = dict(row)
        # Whether an account has a password matters to the owner - those
        # without one can be claimed by anyone who knows the address - but the
        # hash itself never leaves the server.
        has_password = bool(str(row.pop('password_hash', '') or '').strip())
        users.append({**row, 'has_password': has_password})
    return {
        'orders': [dict(o) for o in data['orders']],
        'users': users,
        'pending_ball_count': data['pending_ball_count'],
        'active_order_count': data['active_order_count'],
        'grouped_balls': [dict(row) for row in data['grouped_balls']],
        'statuses': list(ORDER_STATUSES),
        'ball_batch_threshold': config.BALL_BATCH_THRESHOLD,
    }


class BulkStatus(BaseModel):
    order_ids: list[int]
    status: str


@app.post('/api/admin/orders/bulk-status')
def bulk_status(body: BulkStatus, _admin=Depends(require_admin),
                _writable=Depends(require_writable)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Unknown status.')
    if not body.order_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No orders given.')
    db.update_all_orders_status(body.order_ids, body.status)
    return {'ok': True, 'updated': len(body.order_ids), 'status': body.status}


@app.delete('/api/admin/orders/{order_id}')
def remove_order(order_id: int, _admin=Depends(require_admin),
                 _writable=Depends(require_writable)):
    if not db.get_order(order_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'No such order.')
    db.delete_order(order_id)
    return {'ok': True, 'order_id': order_id}


class BalanceChange(BaseModel):
    balance: float


@app.post('/api/admin/users/{user_id}/balance')
def set_balance(user_id: int, body: BalanceChange, _admin=Depends(require_admin),
                _writable=Depends(require_writable)):
    db.update_balance(user_id, body.balance)
    return {'ok': True, 'user_id': user_id, 'balance': body.balance}


@app.post('/api/admin/users/{user_id}/reset-password')
def reset_password(user_id: int, _admin=Depends(require_admin),
                   _writable=Depends(require_writable)):
    """
    Clear a password so the account can set a new one from "First time here?".

    Orders and balance are untouched; this only blanks the hash.
    """
    db.clear_user_password(user_id)
    return {'ok': True, 'user_id': user_id}


@app.post('/api/admin/recheck-ball-batch')
def recheck_ball_batch(_admin=Depends(require_admin), _writable=Depends(require_writable)):
    db.evaluate_ball_batch_notification()
    return {'ok': True}


# --- catalog manager -------------------------------------------------------

IMPORT_MODES = ('add_new', 'refresh', 'replace')


class ProductEdit(BaseModel):
    product_url: str
    name: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    in_stock: Optional[bool] = None
    is_visible: Optional[bool] = None
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    product_type: Optional[str] = None
    image_url: Optional[str] = None


class ProductEdits(BaseModel):
    updates: list[ProductEdit] = Field(default_factory=list)


class StockChange(BaseModel):
    product_urls: list[str] = Field(default_factory=list)
    in_stock: bool


class NewProduct(BaseModel):
    product_url: str
    name: str
    sku: str = ''
    price: float = 0.0
    main_category: str = 'Merchandise'
    sub_category: str = 'Apparel'
    product_type: str = 'general'
    image_url: str = ''


class ProductUrls(BaseModel):
    product_urls: list[str] = Field(default_factory=list)


class CatalogImport(BaseModel):
    csv: str
    mode: str = 'refresh'


def _parse_catalog_csv(text: str) -> list[dict]:
    """
    Scraper CSV text -> rows ready for db.upsert_products().

    Read with the stdlib rather than pandas: this runs in the serverless
    function, where pandas is a bundle the deployment deliberately does not
    carry. The rules themselves are catalog_rows', the same ones the Streamlit
    import and sync_catalog use.
    """
    import csv
    import io

    reader = csv.DictReader(io.StringIO(text))
    missing = catalog_rows.missing_csv_columns(reader.fieldnames or [])
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'That file is missing required columns: {", ".join(missing)}',
        )
    return catalog_rows.rows_from_records(reader)


@app.get('/api/admin/catalog')
def admin_catalog(_admin=Depends(require_admin)):
    """
    Every product, including the hidden and out-of-stock ones a shopper is not
    shown - this is the view the Catalog Manager edits.
    """
    rows = [_decorate(p) for p in db.get_products()]
    return {
        'products': rows,
        'main_categories': sorted({r['main_category'] for r in rows if r['main_category']}),
        'sub_categories': sorted({r['sub_category'] for r in rows if r['sub_category']}),
        'counts': {
            'total': len(rows),
            'in_stock': sum(1 for r in rows if r['in_stock']),
            'visible': sum(1 for r in rows if r['is_visible'] and r['in_stock']),
        },
    }


@app.patch('/api/admin/catalog/products')
def edit_products(body: ProductEdits, admin=Depends(require_admin),
                  _writable=Depends(require_writable)):
    """Apply the Products tab's edits. Only the fields sent are touched."""
    updates = [edit.model_dump(exclude_none=True) for edit in body.updates]
    updates = [u for u in updates if len(u) > 1]  # product_url plus something
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No changes given.')
    applied = db.update_products(updates, updated_by=admin.get('email', ''))
    return {'ok': True, 'updated': applied}


@app.post('/api/admin/catalog/stock')
def bulk_stock(body: StockChange, admin=Depends(require_admin),
               _writable=Depends(require_writable)):
    if not body.product_urls:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No products given.')
    changed = db.set_products_stock(body.product_urls, body.in_stock,
                                    updated_by=admin.get('email', ''))
    return {'ok': True, 'updated': changed, 'in_stock': body.in_stock}


@app.post('/api/admin/catalog/products')
def add_product(body: NewProduct, admin=Depends(require_admin),
                _writable=Depends(require_writable)):
    """
    Add something Storm does not sell - club shirts, raffle items, one-offs.

    Goes in as add_new so it can never overwrite a scraped product that happens
    to share the URL.
    """
    product_url = body.product_url.strip()
    if not product_url or not body.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'A name and a reference are both required.')
    if any(p['product_url'] == product_url for p in db.get_products()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            'That reference is already in the catalog.')

    row = body.model_dump()
    row['product_url'] = product_url
    row['in_stock'] = True
    row['is_visible'] = True
    row['scent'] = ''
    db.upsert_products([row], mode='add_new', updated_by=admin.get('email', ''))
    return {'ok': True, 'product_url': product_url}


@app.post('/api/admin/catalog/products/delete')
def remove_products(body: ProductUrls, _admin=Depends(require_admin),
                    _writable=Depends(require_writable)):
    """
    Delete permanently. Hiding is nearly always better, and the frontend says
    so, but a mistyped hand-added product has to be removable.
    """
    if not body.product_urls:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No products given.')
    return {'ok': True, 'deleted': db.delete_products(body.product_urls)}


@app.post('/api/admin/catalog/import/preview')
def preview_import(body: CatalogImport, _admin=Depends(require_admin)):
    """
    What the file would do, before anyone commits to it. Writes nothing, so it
    is deliberately not behind require_writable - reading a CSV to count rows
    is safe even against production.
    """
    if body.mode not in IMPORT_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Unknown import mode.')
    rows = _parse_catalog_csv(body.csv)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'No usable product rows in that file.')
    return db.preview_upsert(rows, mode=body.mode)


@app.post('/api/admin/catalog/import')
def apply_import(body: CatalogImport, admin=Depends(require_admin),
                 _writable=Depends(require_writable)):
    if body.mode not in IMPORT_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Unknown import mode.')
    rows = _parse_catalog_csv(body.csv)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'No usable product rows in that file.')

    email = admin.get('email', '')
    result = db.upsert_products(rows, mode=body.mode, updated_by=email)
    db.record_catalog_import(body.mode, len(rows), email)
    return {'ok': True, **result}


@app.get('/api/health')
def health():
    """
    Whether this deployment can read, whether it may write, and why not.

    Every field is computed defensively. A health check that raises is the one
    thing this endpoint must never do: a 500 here says only "something broke",
    which is exactly the position this deployment has been stuck in.
    """
    blocked = _write_block_reason()
    body = {
        'ok': True,
        'writes_enabled': blocked is None,
        'writes_blocked_because': blocked,
        'database_url_set': bool(str(getattr(config, 'DATABASE_URL', '') or '')),
        'session_secret_set': bool(os.environ.get('SESSION_SECRET')),
        'cookie_secure': os.environ.get('COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'},
        'startup_error': _startup_error,
        'streamlit_installed': runtime.RUNNING_UNDER_STREAMLIT,
    }
    try:
        body['products'] = db.count_products()
    except Exception as exc:
        body['ok'] = False
        body['products'] = None
        body['database_error'] = _describe(exc)
    return body
