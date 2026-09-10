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

Nothing needs configuring in between: `next.config.mjs` proxies `/api` and
`/static` to the API, at `http://localhost:8000` locally and at the API project
in production. Set `API_ORIGIN` to point the proxy somewhere else.

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

**The browser only ever talks to this origin.** `next.config.mjs` rewrites
`/api` and `/static` to the API project. That is not a convenience: `*.vercel.app`
is on the Public Suffix List, so two subdomains of it are *cross-site*, and the
session cookie is `SameSite=Lax` - which browsers do not send cross-site at all.
Called directly, signing in would look like it worked and every request after it
would be anonymous. `SameSite=None` would send it and then be blocked by Safari,
so the app would be broken on every iPhone on the team. Proxying keeps the
cookie first-party, and costs one hop per request.

`NEXT_PUBLIC_API_BASE` still bypasses the proxy if you set it, which then needs
`CORS_ORIGINS` on the API and a `SameSite=None` cookie.

**Images** are served by the API, from the `static/` directory at the repo root
where the refresh workflow commits them. This app only builds the path, in
`imageSrc()`.

It used to read that directory off the filesystem through
`app/static/[...path]/route.ts`, which works only while both halves share a
checkout. Deployed the way it has to be - its own project rooted at `web/` -
`static/` is outside the root and every product rendered "No image". Copying
12MB into `web/public` would mean two sets drifting apart on every scrape, so
the API mounts the one set and this side proxies to it.

## Deploying

Two Vercel projects from this repo, both on the `stevens-bowling` team:

| Project | Root Directory | URL |
| --- | --- | --- |
| `api` | *(blank)* | `api-stevens-bowling.vercel.app` |
| `web` | `web` | `web-stevens-bowling.vercel.app` |

`.vercelignore` is at the repository root and applies to **both** of them, so
nothing the frontend needs may be listed in it. `web/` was, and the frontend
deployed in twelve milliseconds with no output at all.

Because `web` has a Root Directory, a commit that touches nothing inside it does
not redeploy it. That is correct, and it means a change to `.vercelignore` or to
the API alone leaves the frontend on its previous build.

The API project needs `DATABASE_URL`, `SESSION_SECRET`, `COOKIE_SECURE=1`, and
`ALLOW_PRODUCTION_WRITES=1` when it should take real orders. The web project
needs nothing - it proxies to the API project's URL by default.

Paste `DATABASE_URL` **without quotes**. With them, psycopg stops seeing a URI,
reads the string as keyword/value pairs, splits it at the first `=` and reports
the URL as an unknown connection option. `config.py` strips a matched pair now,
but the dashboard does not show the value back, so it is worth getting right.

`pyproject.toml` names the API's entrypoint (`server.main:app`) and its
dependencies. Vercel's FastAPI detection reads `api/index.py` statically and
cannot see the `app` that file binds inside a try/except, so without that
entrypoint the build fails; and once a `pyproject.toml` exists the build
resolves dependencies from it with uv rather than from `requirements.txt`.

Turn **Deployment Protection off** on the API project. It 302s every request to
`vercel.com/sso-api`, including the browser calls this app makes.
