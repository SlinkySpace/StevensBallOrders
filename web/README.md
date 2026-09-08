# web/ — read-only proof

The bowling order app rendered outside Streamlit, reading the **same Neon
database**, to answer two questions before committing to a port:

1. Can every existing account still log in? — **yes, all 11, no resets**
2. Does the query surface hold up outside Python? — **yes, 437 products and
   every order render correctly**

The Streamlit app in the parent directory is untouched and remains the one the
team orders from. Nothing here writes.

## Running it

```bash
npm --prefix web install
npm --prefix web run dev        # http://localhost:3000
```

Needs `web/.env.local` with `DATABASE_URL=` copied from
`.streamlit/secrets.toml`. That file is gitignored and must stay so — it
carries the Neon password.

Both apps can run at once; they are two readers of one database.

## Checks

```bash
npm --prefix web run check:readonly   # fails if any write statement appears
npm --prefix web run typecheck
python web/scripts/password-compat-fixtures.py    # Python writes hashes
node --experimental-strip-types web/scripts/password-compat.test.ts   # Node verifies them
```

`check:readonly` greps every file for `INSERT`, `UPDATE … SET`, `DELETE`,
`ALTER`, `DROP`, `ON CONFLICT` and friends, and fails the run if one appears.
The read-only promise is enforced, not asserted — this app points at production.

## What is deliberately missing

- **No writes, no sessions, no cart.** Adding those is the actual port; this is
  the evidence that the port is safe to start.
- **No login form.** Proving people can still sign in does not require anyone to
  type a password into an unfinished app. `/signin` reads the *shape* of each
  stored hash instead — algorithm, iteration count, salt and digest lengths —
  and never touches a hash, an email or a password.

## Things a real deployment still has to solve

- **Images.** `app/static/[...path]/route.ts` reads them out of the Python app's
  `static/` directory so 12MB is not duplicated. Vercel only uploads what is
  inside the project root, so a deployed version needs the web app at the repo
  root, or the refresh workflow writing images somewhere the build can see.
- **One data layer, not two.** `sync_catalog.py` writes `products` through
  `db.py`. If the web app grows its own TypeScript writer, `upsert_products`
  exists twice — replace-mode carry-forward, the 10% delete bound, SKU
  re-keying — and a divergence lands on the code that issues
  `DELETE FROM products`. Either keep the write path in Python, or have
  `sync_catalog.py` POST to this app instead of writing directly.
- **Migrations.** `db.init_db()` owns the schema, including the orders → line
  items migration. This app must never run schema management; there is exactly
  one owner.
