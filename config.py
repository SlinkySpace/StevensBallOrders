from pathlib import Path

import runtime

BASE_DIR = Path(__file__).resolve().parent


def _secret(key: str, default=None):
    """
    Read a secret without exploding when there is no secrets.toml.

    Delegates to runtime.secret, which reads st.secrets when running under
    Streamlit and falls back to the environment otherwise - so the same config
    works in the app, in the scraper's sync, and in a serverless function with
    no Streamlit installed.
    """
    return runtime.secret(key, default)


def _secret_bool(key: str, default: bool) -> bool:
    value = _secret(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Local SQLite fallback
DB_PATH = BASE_DIR / 'bowling_orders.db'

def _unquote(value: str) -> str:
    """
    Strip a matched pair of surrounding quotes off an environment value.

    Dashboards and .env files invite pasting a value with the quotes still on
    it, and nothing downstream notices: the string is non-empty, so
    USE_POSTGRES is true and the app starts. psycopg is where it surfaces, and
    badly - a connection string that does not begin with "postgresql://" is
    treated as keyword/value pairs instead of a URI, so it splits on the first
    "=" and reports the URL itself as an unknown option name. No legitimate
    Postgres URI starts with a quote, so removing them is unambiguous.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1].strip()
    return value


# Hosted database option (Neon / Supabase Postgres)
DATABASE_URL = _unquote(str(_secret("DATABASE_URL", "") or ""))

CATALOG_CSV = BASE_DIR / 'storm_products_tagged.csv'

APP_TITLE = 'Team Bowling Order Dashboard'

BALL_BATCH_THRESHOLD = 4
BALL_PENDING_STATUSES = ('submitted', 'approved')

# Owners get the dashboard and the Catalog Manager. Set OWNER_EMAILS in
# .streamlit/secrets.toml to override; the list below is only a fallback so a
# fresh clone still has an admin.
OWNER_EMAILS = tuple(_secret(
    "OWNER_EMAILS",
    [
        'jela@stevens.edu',
        'echin1@stevens.edu',
        'valdridg@stevens.edu',
        'abranco@stevens.edu',
        'cfolgore@stevens.edu',
        'msantos2@stevens.edu',
        'jwang12@stevens.edu',
        'mderosa@stevens.edu',
    ]
))

# Shared code required to create an account or to set a password on an account
# that predates passwords. Leave unset to allow open signup.
TEAM_ACCESS_CODE = str(_secret("TEAM_ACCESS_CODE", "") or "").strip()

MIN_PASSWORD_LENGTH = int(_secret("MIN_PASSWORD_LENGTH", 8) or 8)

# Off unless switched on deliberately. Sending mail is the one action here that
# reaches people outside the app and cannot be taken back, so the default should
# not be the one that does it.
EMAIL_NOTIFICATIONS_ENABLED = _secret_bool("EMAIL_NOTIFICATIONS_ENABLED", False)
SMTP_USERNAME = _secret("SMTP_USERNAME", "") or ""
SMTP_PASSWORD = _secret("SMTP_PASSWORD", "") or ""
SMTP_HOST = _secret("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com"
SMTP_PORT = int(_secret("SMTP_PORT", 587) or 587)
SMTP_USE_TLS = _secret_bool("SMTP_USE_TLS", True)

BALL_WEIGHTS = ['12 lb', '13 lb', '14 lb', '15 lb', '16 lb']
APPAREL_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL']

ACTIVE_ORDER_STATUSES = ('submitted', 'approved', 'ordered')
COMPLETED_ORDER_STATUSES = ('fulfilled',)
