from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'bowling_orders.db'
CATALOG_CSV = BASE_DIR / 'storm_products_tagged.csv'
OWNER_EMAILS = ['jela@stevens.edu', 'echin1@stevens.edu', 'valdridg@stevens.edu', 'abranco@stevens.edu', 'cfolgore@stevens.edu', 'msantos2@stevens.edu', 'jwang12@stevens.edu']
APP_TITLE = 'Team Bowling Order Dashboard'
BALL_BATCH_THRESHOLD = 4
BALL_PENDING_STATUSES = ('submitted', 'approved')
EMAIL_NOTIFICATIONS_ENABLED = True
SMTP_USERNAME = st.secrets["SMTP_USERNAME"]
SMTP_PASSWORD = st.secrets["SMTP_PASSWORD"]
SMTP_HOST = st.secrets["SMTP_HOST"]
SMTP_PORT = st.secrets["SMTP_PORT"]
SMTP_USE_TLS = True

BALL_WEIGHTS = ['12 lb', '13 lb', '14 lb', '15 lb', '16 lb']
APPAREL_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL']

ACTIVE_ORDER_STATUSES = ('submitted', 'approved', 'ordered')
COMPLETED_ORDER_STATUSES = ('fulfilled',)
