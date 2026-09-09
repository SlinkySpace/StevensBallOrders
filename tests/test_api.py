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

print('\n== logout ==')
r = good.post('/api/auth/logout')
check('logout succeeds', r.status_code == 200)
good.cookies.clear()
check('after logout the cart is refused', good.get('/api/cart').status_code == 401)

DB.unlink(missing_ok=True)
print(f'\n{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
