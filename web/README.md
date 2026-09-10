# web/ — the frontend

The Stevens Bowling Team Orders app, built from the Claude Design file in
`design/`. Replaces the Streamlit UI; the backend, database and scraper are
unchanged.

It talks to the Python API and nothing else. `db.py` stays the only writer, so
`upsert_products`, `place_order_items` and the rest exist once and this side
cannot drift from them.

## Running it

Two processes. The API first:

```bash
pip install -r requirements.txt
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
SESSION_SECRET=<that> DATABASE_URL= uvicorn server.main:app --port 8000
```

Then the frontend:

```bash
npm --prefix web install
npm --prefix web run dev
```

`web/.env.local` sets `NEXT_PUBLIC_API_BASE`, which is `http://localhost:8000`
locally and the API's deployed URL in production.

With `DATABASE_URL` blank the API uses a local SQLite file. Pointed at Neon it
**refuses to write** unless `ALLOW_PRODUCTION_WRITES=1` — Streamlit is still the
live app, and a second writer should be a deliberate act.

## Screens

| Route | What it is |
| --- | --- |
| `/signin` | Login, create account, and "first time here?" for accounts that predate passwords |
| `/` | Catalog — search, category filters, 24 per page, add to cart from the card |
| `/cart` | Quantities, weights and notes, with a sticky summary |
| `/checkout` | The order as one table, then place it |
| `/outstanding` | Placed but not fulfilled |
| `/history` | Everything, any state, CSV download |
| `/profile` | Balance, saved card, change password, log out |
| `/owner` | Owners only: ball batch, order management, user balances |

## Things worth knowing

**The cart lives on the server**, in `saved_carts`. It is mirrored in React for
responsiveness and written back on a 500ms debounce, so typing a quantity is not
one request per keystroke. Checkout sends only a note — the server prices the
order from the cart it holds, so this page cannot name its own prices.

**Theme** is an explicit choice, stored per browser, applied by an inline script
before first paint. Without that script there is a light flash on every load for
anyone using dark mode; because the script rewrites `data-theme` before React
hydrates, `<html>` carries `suppressHydrationWarning`.

**Images** are served by `app/static/[...path]/route.ts`, reading the Python
app's `static/` directory. They are committed there by the refresh workflow, and
copying 12MB into `web/public` would mean two sets drifting apart every scrape.
A deployment rooted at `web/` needs "Include files outside the root directory",
or images moved to a CDN.

## Deploying

Two Vercel projects from this repo:

| Project | Root Directory |
| --- | --- |
| API | *(blank)* |
| Web | `web` |

The API project needs `DATABASE_URL`, `SESSION_SECRET`, `COOKIE_SECURE=1`, and
`ALLOW_PRODUCTION_WRITES=1` when it should take real orders. The web project
needs `NEXT_PUBLIC_API_BASE` pointing at the API, and the API needs
`CORS_ORIGINS` pointing back at the web URL.

Turn **Deployment Protection off** on the API project. It 302s every request to
`vercel.com/sso-api`, including the browser calls this app makes.
