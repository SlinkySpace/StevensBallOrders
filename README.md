# Team Bowling Order Dashboard

A Streamlit app for internal discounted bowling product ordering.

## Updating products and stock

**You no longer push to GitHub to change the catalog.** Log in as an owner and
open **Catalog Manager** in the sidebar.

- **Products tab** - edit price, name, SKU, category and product type directly in
  the grid. Untick **In stock** to pull something from the catalog; untick
  **Visible** to hide it without deleting. Press *Save changes*. Shoppers see the
  change on their next page load.
- **Bulk stock update** - filter to a category, then mark everything shown in or
  out of stock in one click.
- **Import from scraper CSV** - when Storm changes their line-up, re-run the
  scraper (below) and upload the CSV here. You get a preview of what's new and
  which prices moved before anything is applied. Three modes:
  - *Add new products only* - never touches what's already there
  - *Refresh* - updates prices, stock and details, but keeps products you've
    hidden hidden (this is the usual choice)
  - *Replace* - wipes the table and reloads from scratch
- **Add / remove** - for items that aren't in the Storm catalog at all (club
  shirts, raffle items).

Products are rows in the database, so edits are live for everyone immediately and
survive redeploys.

### How current is the catalog?

Nothing updates it automatically, and that's a deliberate limitation rather than
an oversight: Storm publishes no price feed, and `storm_scraper.py` drives a real
browser using a saved logged-in session (`storm_auth_state.json`). That session
can't be committed, expires periodically, and needs a human to re-create - so a
scheduled scraper on free hosting would quietly rot rather than keep things
fresh.

What the app does instead is make staleness impossible to miss:

- The Catalog Manager shows **Last edited** and when a scraper CSV was last
  imported, by whom, and in which mode.
- Past `STALE_CATALOG_DAYS` (30 by default, in `catalog_admin.py`) that turns
  into a warning suggesting a re-scrape.
- Every product row carries its own **Last edited** date in the grid, so you can
  sort out which entries nobody has touched since the initial import.

In practice: stock and price corrections you make by hand in the Catalog Manager
as they come up, and a full re-scrape is worth doing when Storm changes their
line-up - roughly each season, or whenever the staleness warning appears.

### Re-scraping the Storm catalog

Only needed when Storm adds or removes products - not for price or stock changes.

```bash
python storm_scraper.py
```

```bash
python label_cleaning.py
```

```bash
python optimize_images.py --delete-originals
```

Then upload `storm_products_tagged.csv` in the Catalog Manager's import tab.

`optimize_images.py` matters: the scraper saves 600x600 uncompressed PNGs at
~1.4 MB each. It converts them to WebP, which took the catalog from 343 MB to
5 MB with no visible quality loss. Skipping it will make the app slow again.
It needs Pillow (`pip install Pillow`), which the app itself does not require.

## Look and feel

Colors, corner radius and fonts live in the `[theme]` block of
`.streamlit/config.toml` - the primary color is Stevens red, and changing it is
one line. The catalog renders as a 3-column grid (`CATALOG_COLUMNS` in `app.py`)
with size/quantity/note tucked into a popover behind each *Add to cart*, which
keeps tiles compact. Columns collapse to a single stack on phones automatically.

The small amount of custom CSS in `app.py` (`CATALOG_CSS`) is deliberately
limited to typography and fixed-height blocks. Square images plus a two-line
clamp on product names make tiles in a row match height on their own, so there's
nothing targeting Streamlit's generated `st-emotion-cache-*` class names, which
change between releases.

## File structure

- `app.py` - Streamlit app and page rendering
- `catalog_admin.py` - the owner-facing Catalog Manager page
- `catalog.py` - catalog loading, product typing, filtering, CSV import parsing
- `db.py` - schema and database helpers (SQLite or Postgres)
- `auth.py` - login/session helpers using `st.session_state`
- `email_utils.py` - order status and batch notification emails
- `config.py` - configuration and secret loading
- `storm_scraper.py` / `label_cleaning.py` - catalog scraping pipeline
- `download_images.py` / `optimize_images.py` - product image pipeline

## Database

Set `DATABASE_URL` in `.streamlit/secrets.toml` to use hosted Postgres (Neon,
Supabase). With it unset the app falls back to a local SQLite file, which is fine
for development but does **not** persist on Streamlit Community Cloud - the
filesystem is wiped on every restart, so a hosted database is required in
production.

### Tables

- **users** - `id`, `first_name`, `last_name`, `email` (unique), `saved_card`,
  `balance_owed`, `created_at`
- **orders** - `id`, `user_id`, customer name/email snapshot, `product_name`,
  `sku`, `option_type`, `option_value`, `quantity`, `unit_price`, `total_price`,
  `image_url`, `product_url`, `note`, `status`, `timestamp`, `main_category`,
  `sub_category`, `product_type`
- **products** - `id`, `product_url` (unique, the natural key), `sku`, `name`,
  `price`, `in_stock`, `is_visible`, `main_category`, `sub_category`,
  `product_type`, `scent`, `image_url`, `updated_at`, `updated_by`
- **saved_carts** - `user_id`, `cart_json`, `updated_at`
- **app_state** - `key`, `value`

On first run, if `products` is empty and `storm_products_tagged.csv` is present,
the catalog is seeded from it automatically.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create `.streamlit/secrets.toml` (never commit it - it's gitignored):

```toml
DATABASE_URL = "postgresql://..."
OWNER_EMAILS = ["you@stevens.edu"]
TEAM_ACCESS_CODE = "pick-something-and-share-it-with-the-team"
EMAIL_NOTIFICATIONS_ENABLED = true
SMTP_USERNAME = "you@gmail.com"
SMTP_PASSWORD = "your-app-password"
```

Every value is optional - the app runs without a secrets file, using SQLite and
the fallback owner list in `config.py` - but leaving `TEAM_ACCESS_CODE` unset
means anyone with the URL can create an account.

3. Run the app:

```bash
streamlit run app.py
```

## Accounts and passwords

Logging in needs an email **and** a password. Passwords are hashed with
PBKDF2-HMAC-SHA256 (600,000 iterations, per-user random salt) using only the
Python standard library, so there's no extra dependency to install. Plaintext
passwords are never stored, and the hash never reaches the browser session.

### Rolling this out to an existing team

Accounts created before passwords existed still work - they just have no
password yet. Each person opens the **First time here?** tab, enters their email
and chooses a password, and keeps all their orders and balance.

Until someone does that, their account can be claimed by anyone who knows the
email address. Two things close that window:

1. **Set `TEAM_ACCESS_CODE`** in `.streamlit/secrets.toml` and share it with the
   team. It's then required both to create an account and to set a password on
   an existing one. Without it, signup is open to anyone with the app's URL.
2. **Get everyone to set their password promptly.** The Owner Dashboard lists
   any account that hasn't, and warns at the top while the code is unset.

### Other behavior

- Five failed logins lock that email for five minutes.
- Wrong password and unknown email return the same message, so the form can't be
  used to find out who has an account.
- Users change their own password under **Profile**.
- Owners can **Reset password** for anyone from the Owner Dashboard, which
  clears the hash so that person re-sets it from the **First time here?** tab.
  Orders and balances are untouched. There is no email-based reset.
- `MIN_PASSWORD_LENGTH` defaults to 8 and can be raised in secrets.

## Admin access

The Owner Dashboard and Catalog Manager appear only for emails in
`OWNER_EMAILS`. Set it in secrets; the list in `config.py` is only a fallback
and is visible in this public repo, so setting it in secrets is worthwhile.

## Email behavior

Customers get an email when their order moves to approved, ordered or fulfilled.
Owners get one when the number of bowling balls in `submitted`/`approved` status
reaches `BALL_BATCH_THRESHOLD` in `config.py`. Set
`EMAIL_NOTIFICATIONS_ENABLED = false` to print emails to the console instead.
