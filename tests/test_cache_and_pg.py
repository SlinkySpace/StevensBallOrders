import os, sys, tempfile
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
config.DB_PATH = Path(tempfile.gettempdir()) / "cache_test.db"
config.DATABASE_URL = ""
config.DB_PATH.unlink(missing_ok=True)

import db
db.DB_PATH = config.DB_PATH
db.USE_POSTGRES = False
import catalog

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

db.init_db()
catalog.bootstrap_catalog_from_csv()

print("== cache invalidation ==")
first = catalog.load_catalog(admin_view=True)
url = first.iloc[0]["product_url"]
before = float(first.iloc[0]["price"])

# Write WITHOUT invalidating - the cache should still show the old value.
db.update_products([{"product_url": url, "price": before + 50}], "tester")
stale = catalog.load_catalog(admin_view=True)
stale_price = float(stale[stale["product_url"] == url].iloc[0]["price"])
check("a write without invalidation still serves the cached price",
      stale_price == before, f"before={before} cached={stale_price}")

catalog.invalidate_catalog_cache()
fresh = catalog.load_catalog(admin_view=True)
fresh_price = float(fresh[fresh["product_url"] == url].iloc[0]["price"])
check("invalidate_catalog_cache() surfaces the new price",
      fresh_price == before + 50, f"expected {before + 50}, got {fresh_price}")

print("\n== shopper view hides out-of-stock immediately ==")
shopper_before = len(catalog.load_catalog())
db.set_products_stock([url], False, "tester")
catalog.invalidate_catalog_cache()
shopper_after = len(catalog.load_catalog())
check("an out-of-stock product leaves the shopper view",
      shopper_after == shopper_before - 1, f"{shopper_before} -> {shopper_after}")

config.DB_PATH.unlink(missing_ok=True)

print("\n== generated Postgres SQL (syntax review) ==")
db.USE_POSTGRES = True
print("-- upsert / refresh --")
cols = list(db.PRODUCT_COLUMNS) + ["updated_at", "updated_by"]
new = "EXCLUDED"
def assign(col):
    if col == "price":
        return f"price = CASE WHEN {new}.price > 0 THEN {new}.price ELSE products.price END"
    if col == "image_url":
        return f"image_url = CASE WHEN {new}.image_url <> '' THEN {new}.image_url ELSE products.image_url END"
    return f"{col} = {new}.{col}"
assignments = ", ".join(assign(c) for c in db.SCRAPED_PRODUCT_COLUMNS)
print(f"INSERT INTO products({', '.join(cols)}) VALUES ({db._placeholders(len(cols))})")
print(f"ON CONFLICT (product_url) DO UPDATE SET {assignments},")
print(f"  updated_at = {new}.updated_at, updated_by = {new}.updated_by;")
print("\n-- grouped pending balls --")
print(db._grouped_pending_ball_query().strip())

db.USE_POSTGRES = False

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
