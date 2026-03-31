# Team Bowling Order Dashboard

A local Streamlit app for internal discounted bowling product ordering.

## File structure

- `app.py` - main Streamlit app and page rendering
- `db.py` - SQLite schema and database helpers
- `catalog.py` - catalog loading, product typing, and filtering
- `auth.py` - lightweight login/session helpers using `st.session_state`
- `email_utils.py` - owner email notification helper
- `config.py` - app configuration
- `requirements.txt` - Python dependencies

## SQLite schema

### users
- `id` INTEGER PRIMARY KEY
- `first_name` TEXT
- `last_name` TEXT
- `email` TEXT UNIQUE
- `saved_card` TEXT
- `balance_owed` REAL
- `created_at` TEXT

### orders
- `id` INTEGER PRIMARY KEY
- `user_id` INTEGER
- `customer_first_name` TEXT
- `customer_last_name` TEXT
- `customer_email` TEXT
- `product_name` TEXT
- `sku` TEXT
- `option_type` TEXT
- `option_value` TEXT
- `quantity` INTEGER
- `unit_price` REAL
- `total_price` REAL
- `image_url` TEXT
- `product_url` TEXT
- `note` TEXT
- `timestamp` TEXT
- `status` TEXT
- `main_category` TEXT
- `sub_category` TEXT
- `product_type` TEXT

### app_state
- `key` TEXT PRIMARY KEY
- `value` TEXT

## Setup

1. Place your cleaned catalog CSV in this folder and name it:
   - `storm_products_tagged.csv`

2. Create a virtual environment if desired.

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Update `config.py` if needed:
   - `OWNER_EMAIL`
   - `CATALOG_CSV`
   - SMTP settings if you want real email sending

5. Run the app:
   ```bash
   streamlit run app.py
   ```

## Admin access

The owner dashboard is shown only when the logged-in email matches `OWNER_EMAIL` in `config.py`.

## Email behavior

By default, `EMAIL_NOTIFICATIONS_ENABLED = False`, so batch emails are printed to the terminal instead of being sent.

The app will notify the owner when the quantity of bowling balls in `submitted` or `approved` status reaches the configured threshold.
