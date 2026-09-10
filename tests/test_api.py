"""
The write API: sessions, authorisation, and the writes themselves.

Runs against a throwaway SQLite file with DATABASE_URL blanked, like every
other test here. It never touches the hosted database.
"""

import os
import sys
import tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP)
sys.path.insert(0, APP)

os.environ['SESSION_SECRET'] = 'test-secret-not-used-anywhere-real'
os.environ['DATABASE_URL'] = ''

import config  # noqa: E402

DB = Path(tempfile.gettempdir()) / 'api_test.db'
DB.unlink(missing_ok=True)
config.DB_PATH = DB
config.DATABASE_URL = ''

import db  # noqa: E402

db.DB_PATH = DB
db.USE_POSTGRES = False

import auth  # noqa: E402

# auth.py binds TEAM_ACCESS_CODE at import. The real one is set in
# secrets.toml, and these tests are about the API rather than that code, so it
# is cleared here - otherwise the suite passes or fails depending on whether
# the machine running it happens to have a secrets file.
auth.TEAM_ACCESS_CODE = ''

results = []


def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f'\n        {extra}' if extra and not cond else ''))


try:
    from fastapi.testclient import TestClient
except ImportError:
    print('SKIP  fastapi is not installed; run: pip install -r api/requirements.txt')
    print('\n0/0 passed (skipped)')
    sys.exit(0)

from server.main import app  # noqa: E402
from server import sessions  # noqa: E402

db.init_db()

# An owner, so the admin routes can be exercised. config.OWNER_EMAILS decides.
OWNER = str(config.OWNER_EMAILS[0]).strip().lower()
SHOPPER = 'shopper@stevens.edu'
PASSWORD = 'bowling123'

client = TestClient(app)


def fresh_client():
    """A client with no cookies, i.e. a signed-out browser."""
    return TestClient(app)


print('== signup and session ==')
r = client.post('/api/auth/signup', json={
    'first_name': 'Sam', 'last_name': 'Shopper', 'email': SHOPPER,
    'password': PASSWORD, 'confirm': PASSWORD, 'access_code': '',
})
check('signup succeeds', r.status_code == 200, f'{r.status_code} {r.text[:120]}')
check('signup sets a session cookie', sessions.COOKIE_NAME in r.cookies,
      str(dict(r.cookies)))
check('signup never returns the password hash', 'password_hash' not in r.text, r.text[:160])

r = client.get('/api/auth/me')
check('the session identifies the user', r.json().get('user', {}).get('email') == SHOPPER, r.text[:160])
check('a shopper is not an admin', r.json().get('is_admin') is False, r.text[:160])

print('\n== signed-out requests are refused ==')
anon = fresh_client()
for method, path in [('get', '/api/cart'), ('get', '/api/orders'), ('post', '/api/orders')]:
    r = getattr(anon, method)(path, **({'json': {}} if method == 'post' else {}))
    check(f'{method.upper()} {path} -> 401', r.status_code == 401, f'got {r.status_code}')

r = anon.get('/api/auth/me')
check('GET /api/auth/me is fine signed out', r.status_code == 200 and r.json()['user'] is None)

print('\n== a forged cookie is rejected ==')
forged = fresh_client()
forged.cookies.set(sessions.COOKIE_NAME, 'eyJlbWFpbCI6ICJhZG1pbkBleGFtcGxlLmNvbSJ9.bogus')
r = forged.get('/api/cart')
check('an unsigned cookie does not authenticate', r.status_code == 401, f'got {r.status_code}')

tampered = fresh_client()
real = sessions.issue(SHOPPER)
body, _, sig = real.partition('.')
tampered.cookies.set(sessions.COOKIE_NAME, body + '.' + ('A' * len(sig)))
r = tampered.get('/api/cart')
check('a tampered signature does not authenticate', r.status_code == 401, f'got {r.status_code}')

print('\n== login ==')
bad = fresh_client()
r = bad.post('/api/auth/login', json={'email': SHOPPER, 'password': 'wrong'})
check('a wrong password is 401', r.status_code == 401, f'got {r.status_code}')
r = bad.post('/api/auth/login', json={'email': 'nobody@stevens.edu', 'password': 'whatever'})
check('an unknown email gives the same 401', r.status_code == 401, f'got {r.status_code}')

good = fresh_client()
r = good.post('/api/auth/login', json={'email': SHOPPER, 'password': PASSWORD})
check('the right password logs in', r.status_code == 200, f'{r.status_code} {r.text[:120]}')

print('\n== the cart is server-held ==')
product = {
    'product_url': 'https://www.stormbowling.com/test-ball', 'name': 'TEST BALL',
    'sku': 'TB1', 'price': 100.0, 'in_stock': True, 'is_visible': True,
    'main_category': 'Equipment', 'sub_category': 'Bowling Balls',
    'product_type': 'bowling_ball', 'scent': '', 'image_url': '',
}
db.upsert_products([product], mode='refresh', updated_by='test')

line = {'product_url': product['product_url'], 'name': product['name'], 'sku': 'TB1',
        'unit_price': 100.0, 'quantity': 2, 'option_type': 'Weight',
        'option_value': '15 lb', 'note': '', 'image_url': '', 'product_type': 'bowling_ball'}

r = good.put('/api/cart', json=[line])
check('the cart saves', r.status_code == 200 and r.json()['lines'] == 1, r.text[:160])
r = good.get('/api/cart')
check('the cart reads back', len(r.json()['cart']) == 1, r.text[:160])

r = good.put('/api/cart', json=[{**line, 'quantity': 999}])
check('an absurd quantity is rejected by validation', r.status_code == 422, f'got {r.status_code}')

print('\n== placing an order ==')
r = good.post('/api/orders', json={'note': 'from the API'})
check('the order is placed', r.status_code == 200 and r.json().get('ok'), r.text[:200])
order_id = r.json().get('order_id')

r = good.get('/api/cart')
check('the cart is emptied afterwards', r.json()['cart'] == [], r.text[:120])

orders = good.get('/api/orders').json()['orders']
check('the order appears in my orders', any(o['id'] == order_id for o in orders), str(len(orders)))
placed = next(o for o in orders if o['id'] == order_id)
check('the total is priced by the server, not the client',
      float(placed['total_price']) == 200.0, str(placed['total_price']))
check('the line items came across', len(placed.get('items', [])) == 1, str(placed.get('items')))

r = good.post('/api/orders', json={'note': 'again'})
check('a second checkout with an empty cart is refused', r.status_code == 400, f'got {r.status_code}')

print('\n== admin routes ==')
r = good.get('/api/admin/orders')
check('a shopper cannot list all orders', r.status_code == 403, f'got {r.status_code}')
r = good.patch(f'/api/admin/orders/{order_id}', json={'status': 'fulfilled'})
check('a shopper cannot change a status', r.status_code == 403, f'got {r.status_code}')

owner = fresh_client()
owner.post('/api/auth/signup', json={
    'first_name': 'Olive', 'last_name': 'Owner', 'email': OWNER,
    'password': PASSWORD, 'confirm': PASSWORD, 'access_code': '',
})
check('the owner is recognised as admin', owner.get('/api/auth/me').json()['is_admin'] is True)

r = owner.get('/api/admin/orders')
check('the owner can list all orders', r.status_code == 200, f'got {r.status_code}')

r = owner.patch(f'/api/admin/orders/{order_id}', json={'status': 'fulfilled'})
check('the owner can set a status', r.status_code == 200, r.text[:160])
check('the status actually changed',
      dict(db.get_order(order_id))['status'] == 'fulfilled',
      dict(db.get_order(order_id))['status'])

r = owner.patch(f'/api/admin/orders/{order_id}', json={'status': 'banana'})
check('an unknown status is refused', r.status_code == 400, f'got {r.status_code}')
r = owner.patch('/api/admin/orders/999999', json={'status': 'fulfilled'})
check('an unknown order is 404', r.status_code == 404, f'got {r.status_code}')

print('\n== catalog manager ==')

CSV_HEADER = 'product_url,name,sku,price,image_url,main_category,sub_category,scent\n'
SEED_CSV = CSV_HEADER + (
    'https://www.stormbowling.com/products/equipment/bowling-balls/bbmvxa-alpha,'
    'Alpha Crux,BBMVXA,$120.00,https://img/a.png,Equipment,Bowling Balls,Apple Fritter\n'
    'https://www.stormbowling.com/products/bowling-essentials/towels/ac909pr-shammy,'
    'Premier Shammy,AC909PR,$13.00,https://img/b.png,Bowling Essentials,Towels,none\n'
)

# Earlier tests already put a product in, so count against that rather than zero.
BASE_PRODUCTS = db.count_products()

r = good.get('/api/admin/catalog')
check('a shopper cannot read the admin catalog', r.status_code == 403, f'got {r.status_code}')
r = good.post('/api/admin/catalog/import', json={'csv': SEED_CSV, 'mode': 'refresh'})
check('a shopper cannot import a catalog', r.status_code == 403, f'got {r.status_code}')

r = owner.post('/api/admin/catalog/import/preview', json={'csv': SEED_CSV, 'mode': 'refresh'})
check('the owner can preview an import', r.status_code == 200, r.text[:200])
preview = r.json() if r.status_code == 200 else {}
check('the preview counts both rows as new', preview.get('new') == 2, str(preview))
check('the preview writes nothing', db.count_products() == BASE_PRODUCTS, str(db.count_products()))

r = owner.post('/api/admin/catalog/import', json={'csv': SEED_CSV, 'mode': 'refresh'})
check('the owner can apply an import', r.status_code == 200, r.text[:200])
check('the products landed', db.count_products() == BASE_PRODUCTS + 2, str(db.count_products()))

r = owner.post('/api/admin/catalog/import/preview', json={'csv': SEED_CSV, 'mode': 'refresh'})
second = r.json() if r.status_code == 200 else {}
check('re-previewing the same file finds nothing new', second.get('new') == 0, str(second))
check('re-previewing recognises both as existing', second.get('existing') == 2, str(second))

DEARER = SEED_CSV.replace('$120.00', '$131.00')
r = owner.post('/api/admin/catalog/import/preview', json={'csv': DEARER, 'mode': 'refresh'})
changes = r.json().get('price_changes', []) if r.status_code == 200 else []
check('a price change is reported', len(changes) == 1, str(changes))
check('the price change reads from -> to',
      changes and changes[0]['from'] == 120.0 and changes[0]['to'] == 131.0, str(changes))

r = owner.post('/api/admin/catalog/import/preview', json={'csv': SEED_CSV, 'mode': 'banana'})
check('an unknown import mode is refused', r.status_code == 400, f'got {r.status_code}')
r = owner.post('/api/admin/catalog/import/preview',
               json={'csv': 'name,price\nthing,1', 'mode': 'refresh'})
check('a file missing required columns is refused', r.status_code == 400, f'got {r.status_code}')

ball = next(p for p in db.get_products() if p['sku'] == 'BBMVXA')
r = owner.patch('/api/admin/catalog/products',
                json={'updates': [{'product_url': ball['product_url'],
                                   'price': 99.5, 'is_visible': False}]})
check('the owner can edit a product', r.status_code == 200, r.text[:200])
edited = next(p for p in db.get_products() if p['sku'] == 'BBMVXA')
check('the price changed', float(edited['price']) == 99.5, str(edited['price']))
check('visibility changed', not edited['is_visible'], str(edited['is_visible']))
check('an edit leaves other fields alone', edited['name'] == 'Alpha Crux', edited['name'])

r = owner.patch('/api/admin/catalog/products', json={'updates': []})
check('an empty edit is refused', r.status_code == 400, f'got {r.status_code}')

r = owner.post('/api/admin/catalog/stock',
               json={'product_urls': [ball['product_url']], 'in_stock': False})
check('bulk stock works', r.status_code == 200, r.text[:200])
check('the product went out of stock',
      not next(p for p in db.get_products() if p['sku'] == 'BBMVXA')['in_stock'])

r = owner.get('/api/admin/catalog')
body = r.json() if r.status_code == 200 else {}
shown = body.get('products', [])
check('the admin catalog includes the hidden product',
      any(p['sku'] == 'BBMVXA' for p in shown), str(len(shown)))
hidden = next((p for p in shown if p['sku'] == 'BBMVXA'), {})
check('it comes back flagged not visible', not hidden.get('is_visible'), str(hidden.get('is_visible')))
check('the visible count excludes it',
      body.get('counts', {}).get('visible') == sum(
          1 for p in shown if p['is_visible'] and p['in_stock']), str(body.get('counts')))
r = good.get('/api/products')
check('a shopper is not shown the hidden product',
      all(p['sku'] != 'BBMVXA' for p in r.json()['products']), r.text[:160])
r = owner.post('/api/admin/catalog/products', json={
    'product_url': 'club-warmup-2026', 'name': 'Club warmup shirt',
    'sku': 'CLUB-WARMUP', 'price': 30.0, 'product_type': 'apparel',
})
check('the owner can add a product by hand', r.status_code == 200, r.text[:200])
check('the hand-added product is in the catalog', db.count_products() == BASE_PRODUCTS + 3, str(db.count_products()))
r = owner.post('/api/admin/catalog/products', json={
    'product_url': 'club-warmup-2026', 'name': 'Club warmup shirt again',
})
check('a duplicate reference is refused', r.status_code == 409, f'got {r.status_code}')

r = owner.post('/api/admin/catalog/products/delete',
               json={'product_urls': ['club-warmup-2026']})
check('the owner can delete a product', r.status_code == 200, r.text[:200])
check('it is gone', db.count_products() == BASE_PRODUCTS + 2, str(db.count_products()))

print('\n== out of stock and unpriced are not offered ==')
# Storm drops the price from a product page when the item cannot be ordered, so
# out of stock and price 0 arrive together - but upsert_products keeps the last
# known price when a scrape reports 0, so an item can also sell out with its
# price intact. Both have to be kept out of the catalog, and the two cases are
# checked separately because either clause alone would pass with only one of
# them present.
db.upsert_products([
    {**product, 'product_url': 'https://www.stormbowling.com/sold-out',
     'name': 'SOLD OUT BALL', 'sku': 'SOLD1', 'price': 189.0, 'in_stock': False},
    {**product, 'product_url': 'https://www.stormbowling.com/no-price',
     'name': 'UNPRICED BALL', 'sku': 'NOPRICE1', 'price': 0.0, 'in_stock': True},
], mode='refresh', updated_by='test')

shopper_skus = {p['sku'] for p in good.get('/api/products').json()['products']}
check('an out-of-stock product is not offered', 'SOLD1' not in shopper_skus)
check('a product with no price is not offered', 'NOPRICE1' not in shopper_skus)
check('a normal product still is', 'TB1' in shopper_skus, str(len(shopper_skus)))

admin_skus = {p['sku'] for p in owner.get('/api/admin/catalog').json()['products']}
check('the Catalog Manager still lists both, so a price can be fixed',
      {'SOLD1', 'NOPRICE1'} <= admin_skus, str(len(admin_skus)))

print('\n== health ==')
r = fresh_client().get('/api/health')
check('health answers signed out', r.status_code == 200, f'got {r.status_code}')
body = r.json() if r.status_code == 200 else {}
check('health reports the product count', isinstance(body.get('products'), int), str(body))
check('health reports whether writes are allowed', body.get('writes_enabled') is True, str(body))
check('health reports whether config is present',
      'database_url_set' in body and 'session_secret_set' in body, str(body))

# The endpoint has to survive the database being unreachable: a 500 here says
# only "something broke", which is what a misconfigured deployment already
# looks like from the outside.
_saved_count = db.count_products


def _explode():
    raise RuntimeError('database is unreachable')


db.count_products = _explode
try:
    r = fresh_client().get('/api/health')
    check('health still answers when the database is down',
          r.status_code == 200, f'got {r.status_code}')
    broken = r.json() if r.status_code == 200 else {}
    check('it says it is not ok', broken.get('ok') is False, str(broken))
    check('it names the database failure',
          'database is unreachable' in str(broken.get('database_error', '')), str(broken))
finally:
    db.count_products = _saved_count

def _leak():
    raise RuntimeError(
        'invalid connection option "postgresql://neondb_owner:hunter2@'
        'ep-example.us-east-1.aws.neon.tech/neondb?sslmode=require"')


db.count_products = _leak
try:
    leaked = fresh_client().get('/api/health').json()
    detail = str(leaked.get('database_error', ''))
    check('health never echoes a database password',
          'hunter2' not in detail, detail)
    check('it still says which error it was',
          'invalid connection option' in detail, detail)
finally:
    db.count_products = _saved_count

print('\n== catalog images ==')
# Named <id>_<content hash>.webp by download_images.py, so a changed image is a
# changed URL - which is what makes immutable safe, and what makes the default
# must-revalidate a wasted round trip per image per page load.
_img = next(iter(sorted(Path(APP).glob('static/catalog_images/*.webp'))), None)
if _img is None:
    check('there are catalog images to serve', False, 'static/catalog_images is empty')
else:
    r = anon.get(f'/static/catalog_images/{_img.name}')
    check('an image is served', r.status_code == 200, f'got {r.status_code}')
    check('it is typed as webp, not octet-stream',
          r.headers.get('content-type') == 'image/webp',
          str(r.headers.get('content-type')))
    check('it is cached as immutable',
          'immutable' in r.headers.get('cache-control', ''),
          str(r.headers.get('cache-control')))

print('\n== logout ==')
r = good.post('/api/auth/logout')
check('logout succeeds', r.status_code == 200)
good.cookies.clear()
check('after logout the cart is refused', good.get('/api/cart').status_code == 401)

DB.unlink(missing_ok=True)
print(f'\n{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
