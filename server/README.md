# api/ — the write path

Every write to the database goes through `db.py`, the same module the Streamlit
app and `sync_catalog.py` use. That is the whole point: there is **one**
implementation of `upsert_products`, `place_order_items` and the rest, so a
second front end cannot drift from it on the code that deletes rows and charges
people.

A front end may read straight from Postgres. A wrong read renders a wrong page,
which is recoverable; a wrong write is not.

## Running it

```bash
pip install -r api/requirements.txt
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SESSION_SECRET
SESSION_SECRET=<that> uvicorn server.main:app --reload --port 8000
```

**It refuses to start against the hosted database** unless
`ALLOW_PRODUCTION_WRITES=1` is set. Streamlit is still the live app, this
service is not in front of anyone yet, and the default has to be that running
it locally cannot write to the database the team is ordering from.

With `DATABASE_URL` blank it uses the local SQLite file and starts freely.

## Sessions

`st.session_state` is gone, so sessions are signed cookies: HMAC-SHA256 over the
email and issue time, stdlib only, nothing stored server-side. That is what lets
this run on serverless, where there is no process to keep state in — the same
reason `db.py`'s cached connection pool cannot survive.

The cookie carries an email and a timestamp, never a password, hash or balance.
Everything else is re-read from the database on each request, so a stale cookie
cannot carry stale money. It is `HttpOnly` and `SameSite=Lax`; set
`COOKIE_SECURE=1` behind HTTPS.

## What it deliberately does not trust

`POST /api/orders` takes only a note. The cart is read from the **database**,
not the request body, so the price charged is the price the server holds — a
client that posted its own line items could otherwise name its own prices.
There is a test for exactly that.

## Endpoints

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/auth/login` `/signup` `/claim` `/logout` | anyone |
| GET | `/api/auth/me` | anyone (null when signed out) |
| POST | `/api/auth/password` | signed in |
| GET/PUT | `/api/cart` | signed in |
| GET/POST | `/api/orders` | signed in |
| GET | `/api/admin/orders` | owners |
| PATCH | `/api/admin/orders/{id}` | owners |

Owners are decided by `OWNER_EMAILS` in `config.py`, via `auth.is_owner_email`.

## Tests

```bash
python tests/test_api.py
```

33 assertions against a throwaway SQLite file — sessions, forged and tampered
cookies, authorisation, server-side pricing, and the writes themselves. Part of
`tests/run_all.py`, so it runs in CI and before every catalog refresh.
