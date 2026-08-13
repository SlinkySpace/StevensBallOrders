"""Smoke test for the DB-backed catalog against a throwaway SQLite file."""
import os
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
os.chdir(APP)
sys.path.insert(0, str(APP))

# Point config at a scratch DB before anything imports it.
import config
config.DB_PATH = Path(tempfile.gettempdir()) / "catalog_smoke_test.db"
config.DATABASE_URL = ""
if config.DB_PATH.exists():
    config.DB_PATH.unlink()

import db
db.DB_PATH = config.DB_PATH
db.USE_POSTGRES = False

import pandas as pd
import catalog

print("== init_db ==")
db.init_db()
with db.get_conn() as _c:
    _tables = sorted(r["name"] for r in _c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall())
print("tables:", _tables)

print("\n== bootstrap from CSV ==")
n = catalog.bootstrap_catalog_from_csv()
print(f"inserted {n} products, count_products={db.count_products()}")

print("\n== SKU repair ==")
prods = {p["name"]: p for p in db.get_products()}
for name in ("ION PRO", "STORM NATION TEE RED", "PTLP HAT"):
    p = prods.get(name)
    print(f"  {name:<24} sku={p['sku'] if p else 'MISSING'}")
bad = [p for p in db.get_products() if " " in p["sku"]]
print(f"  SKUs still containing whitespace: {len(bad)}")

print("\n== stock parsing ==")
all_p = db.get_products()
oos = [p for p in all_p if not p["in_stock"]]
print(f"  out of stock: {len(oos)} (expected 20)")
print(f"  in stock:     {len(all_p) - len(oos)}")
print(f"  sample OOS:   {oos[0]['name']!r} price={oos[0]['price']}")

print("\n== shopper vs admin view ==")
shopper = catalog.load_catalog(admin_view=False)
admin = catalog.load_catalog(admin_view=True)
print(f"  shopper rows: {len(shopper)}  admin rows: {len(admin)}")
print(f"  product_type counts:\n{admin['product_type'].value_counts().to_string()}")

print("\n== filtering ==")
f = catalog.filter_catalog(shopper, "storm", "All", "All")
print(f"  search 'storm' -> {len(f)} rows")
f2 = catalog.filter_catalog(shopper, "", "Equipment", "Bowling Balls")
print(f"  Equipment/Bowling Balls -> {len(f2)} rows")
f3 = catalog.filter_catalog(shopper, "3 ball (rolling)", "All", "All")
print(f"  regex-hostile search '3 ball (rolling)' -> {len(f3)} rows (no crash)")

print("\n== admin edit round-trip ==")
target = admin.iloc[0]["product_url"]
db.update_products([{"product_url": target, "price": 99.99, "in_stock": False}], "tester")
after = [p for p in db.get_products() if p["product_url"] == target][0]
print(f"  price={after['price']} in_stock={after['in_stock']} by={after['updated_by']}")

print("\n== re-import must not clobber the manual price ==")
# Mark it back in stock so 'refresh' sees a real incoming price of 0 for OOS rows.
db.update_products([{"product_url": target, "in_stock": True}], "tester")
res = catalog.import_catalog_csv(pd.read_csv("storm_products_tagged.csv"),
                                mode="refresh", updated_by="reimport")
print(f"  {res}")
after2 = [p for p in db.get_products() if p["product_url"] == target][0]
print(f"  price after refresh = {after2['price']} (CSV value wins on refresh: expected)")

print("\n== add_new is non-destructive ==")
db.update_products([{"product_url": target, "price": 123.45}], "tester")
res2 = catalog.import_catalog_csv(pd.read_csv("storm_products_tagged.csv"),
                                  mode="add_new", updated_by="reimport")
after3 = [p for p in db.get_products() if p["product_url"] == target][0]
print(f"  {res2}")
print(f"  price preserved = {after3['price']} (expected 123.45)")

print("\n== OUT_OF_STOCK refresh keeps known price ==")
oos_url = oos[0]["product_url"]
db.update_products([{"product_url": oos_url, "price": 55.0}], "tester")
catalog.import_catalog_csv(pd.read_csv("storm_products_tagged.csv"),
                           mode="refresh", updated_by="reimport")
after4 = [p for p in db.get_products() if p["product_url"] == oos_url][0]
print(f"  price = {after4['price']} (expected 55.0, not zeroed), in_stock={after4['in_stock']}")

print("\n== bulk stock toggle ==")
urls = [p["product_url"] for p in db.get_products()[:5]]
db.set_products_stock(urls, False, "tester")
still = [p for p in db.get_products() if p["product_url"] in urls and p["in_stock"]]
print(f"  5 toggled off, still in stock: {len(still)} (expected 0)")

print("\n== replace mode ==")
res3 = catalog.import_catalog_csv(pd.read_csv("storm_products_tagged.csv"),
                                  mode="replace", updated_by="reimport")
print(f"  {res3}, count={db.count_products()}")

config.DB_PATH.unlink(missing_ok=True)
print("\nALL CHECKS RAN")
