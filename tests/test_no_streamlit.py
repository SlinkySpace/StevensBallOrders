"""
The shared modules must work where Streamlit is not installed.

This is what a Vercel serverless function is: fastapi, psycopg and nothing
else. The first deploy crashed with FUNCTION_INVOCATION_FAILED because db.py
imported streamlit, which was not in api/requirements.txt.

Streamlit is blocked from importing here to reproduce that environment
faithfully, rather than trusting that the shim works.
"""

import os
import sys
import tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP)
sys.path.insert(0, APP)

results = []


def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f'\n        {extra}' if extra and not cond else ''))


class _BlockStreamlit:
    """Makes `import streamlit` fail, the way it does on a bare function."""

    def find_module(self, name, path=None):  # legacy API, harmless
        return self if name == 'streamlit' or name.startswith('streamlit.') else None

    def find_spec(self, name, path=None, target=None):
        if name == 'streamlit' or name.startswith('streamlit.'):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return None


# Drop anything already imported, then block it.
for name in [m for m in list(sys.modules) if m == 'streamlit' or m.startswith('streamlit.')]:
    del sys.modules[name]
for name in ('runtime', 'config', 'db', 'auth', 'email_utils'):
    sys.modules.pop(name, None)

sys.meta_path.insert(0, _BlockStreamlit())

os.environ['SESSION_SECRET'] = 'test-secret-not-used-anywhere-real'
os.environ['DATABASE_URL'] = ''

print('== the shared modules import without Streamlit ==')
try:
    import runtime
    check('runtime imports', True)
    check('it knows Streamlit is absent', runtime.RUNNING_UNDER_STREAMLIT is False)
except Exception as exc:
    check('runtime imports', False, repr(exc))
    print(f'\n{sum(results)}/{len(results)} passed')
    sys.exit(1)

for module in ('config', 'db', 'auth', 'email_utils'):
    try:
        __import__(module)
        check(f'{module} imports', True)
    except Exception as exc:
        check(f'{module} imports', False, repr(exc))

check('streamlit really was not loaded', 'streamlit' not in sys.modules,
      str([m for m in sys.modules if m.startswith('streamlit')]))

print('\n== and they actually work ==')
import config  # noqa: E402

DB = Path(tempfile.gettempdir()) / 'no_streamlit_test.db'
DB.unlink(missing_ok=True)
config.DB_PATH = DB
config.DATABASE_URL = ''

import db  # noqa: E402
import auth  # noqa: E402

db.DB_PATH = DB
db.USE_POSTGRES = False
auth.TEAM_ACCESS_CODE = ''

db.init_db()
check('init_db builds the schema', True)

created = db.create_user('No', 'Streamlit', 'bare@stevens.edu',
                         auth.hash_password('bowling123'))
check('a user can be created', bool(created))

user, error = auth.authenticate('bare@stevens.edu', 'bowling123')
check('authenticate() works off-Streamlit', user is not None, error)

user, error = auth.authenticate('bare@stevens.edu', 'wrong')
check('a wrong password is still refused', user is None)

db.upsert_products([{
    'product_url': 'https://www.stormbowling.com/bare-ball', 'sku': 'BB9',
    'name': 'BARE BALL', 'price': 100.0, 'in_stock': True, 'is_visible': True,
    'main_category': 'Equipment', 'sub_category': 'Bowling Balls',
    'product_type': 'bowling_ball', 'scent': '', 'image_url': '',
}], mode='refresh', updated_by='test')
check('products can be written', db.count_products() == 1, str(db.count_products()))

print('\n== the connection-pool cache still memoises ==')
check('_get_pool returns the same object twice', db._get_pool() is db._get_pool())

print('\n== session state refuses rather than leaking ==')
# A module-level dict would be per-process, and a warm serverless container
# serves many users from one process, so a silent fallback would hand one
# person's session to the next request.
try:
    runtime.session_state['user'] = {'email': 'someone@example.com'}
    check('writing session state raises', False, 'it silently accepted a write')
except RuntimeError:
    check('writing session state raises', True)

try:
    runtime.session_state.get('user')
    check('reading session state raises', False, 'it silently returned a value')
except RuntimeError:
    check('reading session state raises', True)

print('\n== the write API imports and answers ==')
try:
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    r = client.get('/api/auth/me')
    check('GET /api/auth/me works with no Streamlit installed',
          r.status_code == 200 and r.json()['user'] is None, f'{r.status_code} {r.text[:120]}')
except ImportError as exc:
    check('fastapi is installed', False, repr(exc))
except Exception as exc:
    check('the API starts without Streamlit', False, repr(exc))

DB.unlink(missing_ok=True)
print(f'\n{sum(results)}/{len(results)} passed')
sys.exit(0 if all(results) else 1)
