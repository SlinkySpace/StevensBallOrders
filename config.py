from pathlib import Path
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / 'bowling_orders.db'
CATALOG_CSV = BASE_DIR / 'storm_products_tagged.csv'

APP_TITLE = 'Team Bowling Order Dashboard'

BALL_BATCH_THRESHOLD = 4
BALL_PENDING_STATUSES = ('submitted', 'approved')

OWNER_EMAILS = tuple(st.secrets.get(
    "OWNER_EMAILS",
    ['jela@stevens.edu', 'echin1@stevens.edu', 'valdridg@stevens.edu', 'abranco@stevens.edu', 'cfolgore@stevens.edu', 'msantos2@stevens.edu', 'jwang12@stevens.edu']
))

EMAIL_NOTIFICATIONS_ENABLED = bool(st.secrets.get("EMAIL_NOTIFICATIONS_ENABLED", True))
SMTP_USERNAME = st.secrets.get("SMTP_USERNAME", "")
SMTP_PASSWORD = st.secrets.get("SMTP_PASSWORD", "")
SMTP_HOST = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(st.secrets.get("SMTP_PORT", 587))
SMTP_USE_TLS = bool(st.secrets.get("SMTP_USE_TLS", True))

BALL_WEIGHTS = ['12 lb', '13 lb', '14 lb', '15 lb', '16 lb']
APPAREL_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL']

ACTIVE_ORDER_STATUSES = ('submitted', 'approved', 'ordered')
COMPLETED_ORDER_STATUSES = ('fulfilled',)
