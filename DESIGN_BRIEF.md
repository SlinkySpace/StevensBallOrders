# Design brief — Team Bowling Order Dashboard

Paste this to Claude alongside the repo when you want a visual pass.

---

## What this is

A Streamlit app the Stevens bowling team uses to order Storm equipment at
sponsor prices. Roughly 15–20 teammates browse a ~450-product catalog, add to a
cart, and check out; a handful of owners then approve orders and place them with
Storm in batches. It is not a public store — everyone signing in already knows
what the app is for.

Live on Streamlit Community Cloud (free tier), Streamlit 1.55.

## What I want

Make it look considered rather than defaulty, without changing what it does.
Priority order:

1. **The catalog grid** (`render_product_card`, `render_catalog_page` in
   `app.py`) — this is where everyone spends their time.
2. **The sign-in page** (`render_auth_page`) — first impression, currently three
   bare tabs.
3. **Cart and checkout** (`render_cart_page`, `render_checkout_page`) — the
   checkout is still a plain `st.table`.
4. **The owner dashboard** (`render_owner_dashboard`) — dense and functional;
   worth making scannable, lowest priority.

## Constraints, and why

- **Streamlit only.** No React components, no rewrite, no new runtime
  dependencies. It has to keep deploying to the free tier unchanged.
- **Theme tokens first.** Colors, radii and fonts belong in the `[theme]` block
  of `.streamlit/config.toml`, which already carries a light and dark palette.
  Change values there before reaching for CSS.
- **CSS may target `[data-testid]` attributes and my own class names only.**
  Never `st-emotion-cache-*` — those hashes change between Streamlit releases and
  any rule keyed to them silently dies on upgrade.
- **Don't break tile alignment.** Product tiles line up because the image is
  `aspect-ratio: 1/1` and the name is clamped to two lines with a `min-height`.
  That is deliberate: it avoids flexbox rules aimed at Streamlit's internals.
  Any replacement must survive a Streamlit upgrade the same way.
- **Keep it fast.** Every product card is an `st.fragment` so changing a quantity
  reruns one card, not the page. Images are lazy-loaded `<img>` tags served from
  `app/static/...`, never `st.image` — that was a deliberate fix for a 343 MB
  image problem. Don't undo either.
- **Mobile matters.** People order from their phones at the alley. Columns
  currently collapse to a single stack at 375px with no horizontal scroll.
- **Dark mode must keep working.** Both palettes are defined; don't hardcode a
  color that only reads on one.

## Current state

- 3-column grid, 24 per page (`CATALOG_COLUMNS`, `CATALOG_ITEMS_PER_PAGE`)
- Each tile: square image, 2-line clamped name, price, SKU, and an `st.popover`
  behind "Add to cart" holding weight/size, quantity and a note
- Sidebar: balance owed, nav with emoji, live cart count and total
- Theme: Stevens red `#A32638`, 0.6rem radii, light and dark palettes
- The small CSS block lives in `CATALOG_CSS` at the top of `app.py`

## Known rough edges

- The sign-in page is three unstyled tabs with no visual identity at all
- Checkout renders a raw `st.table` that ignores the theme
- Product tiles show price and SKU with no hierarchy — the SKU competes with the
  price for attention
- Some products legitimately have no photo and fall back to a "No image" box;
  it looks broken rather than intentional
- Out-of-stock products are hidden entirely rather than shown as unavailable
- The owner dashboard is a long unbroken scroll of order cards

## What I'd rather you didn't do

- Don't add a landing/marketing page. Everyone signing in already knows what
  this is.
- Don't introduce a logo or wordmark for Storm or Stevens — I don't have rights
  cleared for either.
- Don't restyle the Catalog Manager's `st.data_editor` grid. It is a working
  spreadsheet and people are used to it.
- Don't change copy that states money, stock or order status. Those wordings are
  deliberate.

## How to verify

`.claude/launch.json` has a `bowling-app` entry, so the app can be started and
driven in the browser. Check both light and dark, and at 375px width. Sign-in is
email plus password; ask me for a test account rather than creating one, since
accounts are real rows.

Show me before/after screenshots of the catalog grid at desktop and mobile
before going further than that.
