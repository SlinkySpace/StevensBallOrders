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
| `/product` | One product in full, by `?ref=<product_url>` — options, quantity, note |
| `/profile` | Balance, saved card, change password, log out |
| `/owner` | Owners only: ball batch, order management, user balances |
| `/manager` | Owners only: prices and stock, CSV import with a diff preview, one-offs |

## Things worth knowing

**The cart lives on the server**, in `saved_carts`. It is mirrored in React for
responsiveness and written back on a 500ms debounce, so typing a quantity is not
one request per keystroke. Checkout sends only a note — the server prices the
order from the cart it holds, so this page cannot name its own prices.

**Theme** is an explicit choice, stored per browser, applied by an inline script
before first paint. Without that script there is a light flash on every load for
anyone using dark mode; because the script rewrites `data-theme` before React
hydrates, `<html>` carries `suppressHydrationWarning`.

**Images** are served by the API, from the `static/` directory at the repo root
where the refresh workflow commits them. This app only builds the URL, in
`imageSrc()`, against `NEXT_PUBLIC_API_BASE`.

It used to read that directory off the filesystem through
`app/static/[...path]/route.ts`, which works only while both halves share a
checkout. Deployed the way it has to be - its own project rooted at `web/` -
`static/` is outside the root and every product rendered "No image". Copying
12MB into `web/public` would mean two sets drifting apart on every scrape, so
the API mounts the one set instead and this side needs nothing but an API URL.

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

`pyproject.toml` names the API's entrypoint (`server.main:app`) and its
dependencies. Vercel's FastAPI detection reads `api/index.py` statically and
cannot see the `app` that file binds inside a try/except, so without that
entrypoint the build fails; and once a `pyproject.toml` exists the build
resolves dependencies from it with uv rather than from `requirements.txt`.

Turn **Deployment Protection off** on the API project. It 302s every request to
`vercel.com/sso-api`, including the browser calls this app makes.
