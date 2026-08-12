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

### Refreshing prices and stock from Storm

One command, from the project folder:

```powershell
.\scripts\refresh-storm-login.ps1
```

A browser opens; log in to stormbowling.com, come back and press Enter. The
script uploads the session to GitHub and starts the scrape **in Actions**, so
nothing runs on your machine and there is no file to upload afterwards. It takes
about 40 minutes and it's free - public repositories get unlimited Actions
minutes.

That defaults to a **dry run**: it checks everything and reports what it would
change without touching the database. If the report looks right:

```powershell
.\scripts\refresh-storm-login.ps1 -Reuse -Apply
```

`-Reuse` skips the browser and reuses the session you just captured.

**Why this isn't on a schedule.** Storm's session cookies are short-lived - one
expires within the hour - so a weekly cron would reliably find the saved login
stale and scrape public retail prices instead of the team's sponsor prices. The
guards would catch it and the run would fail, every week. Signing in immediately
before the scrape avoids the problem entirely. The Catalog Manager's staleness
warning is the reminder to do it. To go back to a schedule anyway, uncomment the
`cron` block at the top of the workflow.

Two repository secrets are required (**Settings → Secrets and variables →
Actions**), both set for you by the script above except `DATABASE_URL`:

| Secret | Value |
| --- | --- |
| `DATABASE_URL` | the same Neon connection string the app uses |
| `STORM_AUTH_STATE` | the entire contents of `storm_auth_state.json` |

To produce `STORM_AUTH_STATE` the first time:

```bash
SCRAPER_SETUP_LOGIN=true python storm_scraper.py
```

A browser opens; log in to stormbowling.com, come back to the terminal and press
Enter. Paste the contents of the generated `storm_auth_state.json` into the
secret. That file is gitignored and must never be committed - it *is* a logged-in
session.

**The saved session will expire eventually.** That's the important failure mode,
because the scraper doesn't error when it happens - it just sees Storm as a
logged-out visitor, which means **retail prices instead of your sponsor prices**.
Writing those to the database would quietly overcharge the whole team.

So `sync_catalog.py` refuses to write when the scraped data looks wrong:

- fewer than 300 usable rows - the scrape broke partway through
- more than 25% of prices changed - the signature of a logged-out scrape
- more than 40% of the file has no price at all - same cause

A tripped guard writes nothing, fails the run, and opens a GitHub issue with
instructions (subsequent failures comment on the existing issue rather than
opening more). The catalog in the app is left exactly as it was. The scraped CSVs
are attached to every run as an artifact so you can see what actually came back.

If a genuine bulk repricing trips the guard, either raise the threshold for one
run via the workflow's `max_price_drift` input, or just import the CSV by hand
from the Catalog Manager where you get a diff preview first.

To sync manually:

```bash
DATABASE_URL="postgresql://..." python sync_catalog.py --dry-run
```

### How current is the catalog?

Between weekly runs, nothing updates it - and day-to-day stock changes are
usually faster to make by hand in the Catalog Manager anyway.

The app makes staleness visible rather than assuming it away:

- The Catalog Manager shows **Last edited** and when a scraper CSV was last
  imported, by whom, and in which mode.
- Past `STALE_CATALOG_DAYS` (30 by default, in `catalog_admin.py`) that turns
  into a warning suggesting a re-scrape.
- Every product row carries its own **Last edited** date in the grid, so you can
  sort out which entries nobody has touched since the initial import.

### Re-scraping by hand

The weekly workflow does this for you. Run it locally only if you want the
images refreshed too, or if you're debugging the scraper.

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
- `sync_catalog.py` - loads a scraper CSV into the database, with the guards that
  stop an expired login from writing retail prices
- `.github/workflows/refresh-catalog.yml` - the weekly automated refresh

## Database

Set `DATABASE_URL` in `.streamlit/secrets.toml` to use hosted Postgres (Neon,
Supabase). With it unset the app falls back to a local SQLite file, which is fine
for development but does **not** persist on Streamlit Community Cloud - the
filesystem is wiped on every restart, so a hosted database is required in
production.

### Tables

- **users** - `id`, `first_name`, `last_name`, `email` (unique), `saved_card`,
  `balance_owed`, `created_at`
- **orders** - `id`, `user_id`, customer name/email snapshot, `note` (the
  checkout note), `total_price`, `status`, `timestamp`. One row per checkout.
- **order_items** - `id`, `order_id`, `product_name`, `sku`, `option_type`,
  `option_value`, `quantity`, `unit_price`, `total_price`, `image_url`,
  `product_url`, `note`, `main_category`, `sub_category`, `product_type`. One
  row per line in the cart.

  Status lives on the order, not the item, so a five-item order is approved once
  and sends one email. It used to be one row per item, which meant five separate
  "orders" to update and five emails. Databases created before that change are
  migrated on first run: rows are regrouped into baskets by `user_id` plus
  `timestamp`, and the old table is kept as `orders_legacy_backup` rather than
  dropped.
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
