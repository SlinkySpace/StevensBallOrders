"""SKU re-keying, tested against the real CI scrape where Storm had moved
their product URLs."""
import os, sys, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
SCRAPE = Path(sys.argv[1]) if len(sys.argv) > 1 else None
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "rekey_test.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""

import db
db.DB_PATH = DB; db.USE_POSTGRES = False
import pandas as pd, catalog

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

db.init_db()

print("== seed the catalog from the stored CSV ==")
catalog.import_catalog_csv(pd.read_csv('storm_products_tagged.csv'), mode='add_new', updated_by='seed')
seeded = db.count_products()
print(f"   seeded {seeded} products")

print("\n== unit: _usable_sku ==")
check("rejects scraper junk with spaces", db._usable_sku('Shopping Cart Cart is Empty') == '')
check("rejects blank / nan", db._usable_sku('') == '' and db._usable_sku('nan') == '')
check("accepts a real SKU, uppercased", db._usable_sku(' bbmveq ') == 'BBMVEQ')
check("accepts underscored SKUs", db._usable_sku('REACTA_CLEAN') == 'REACTA_CLEAN')

print("\n== re-key a product that moved URL ==")
moved = [{
    'product_url': 'https://www.stormbowling.com/master-non-slip-grip-cream',  # new root URL
    'sku': 'M1142', 'name': 'MASTER NON-SLIP GRIP CREAM', 'price': 4.25,
    'in_stock': True, 'is_visible': True, 'main_category': 'Bowling Essentials',
    'sub_category': 'Grip Aids', 'product_type': 'general', 'scent': '', 'image_url': '',
}]
before = db.count_products()
res = db.upsert_products(moved, mode='refresh', updated_by='test')
after = db.count_products()
check("no duplicate created", after == before, f"{before} -> {after}")
row = [p for p in db.get_products() if db._usable_sku(p['sku']) == 'M1142']
check("exactly one row for that SKU", len(row) == 1, str(len(row)))
check("price updated in place", row and abs(float(row[0]['price']) - 4.25) < 0.01,
      str(row[0]['price']) if row else 'missing')

print("\n== a genuinely new product still inserts ==")
fresh = [{
    'product_url': 'https://www.stormbowling.com/brand-new-thing',
    'sku': 'ZZZ999', 'name': 'BRAND NEW THING', 'price': 10.0, 'in_stock': True,
    'is_visible': True, 'main_category': 'X', 'sub_category': 'Y',
    'product_type': 'general', 'scent': '', 'image_url': '',
}]
before = db.count_products()
db.upsert_products(fresh, mode='refresh', updated_by='test')
check("count grew by one", db.count_products() == before + 1)

print("\n== junk SKUs must not collide ==")
junk = [
    {'product_url': 'https://www.stormbowling.com/junk-a', 'sku': 'Shopping Cart Cart is Empty',
     'name': 'JUNK A', 'price': 1.0, 'in_stock': True, 'is_visible': True,
     'main_category': 'X', 'sub_category': 'Y', 'product_type': 'general', 'scent': '', 'image_url': ''},
    {'product_url': 'https://www.stormbowling.com/junk-b', 'sku': 'Shopping Cart Cart is Empty',
     'name': 'JUNK B', 'price': 2.0, 'in_stock': True, 'is_visible': True,
     'main_category': 'X', 'sub_category': 'Y', 'product_type': 'general', 'scent': '', 'image_url': ''},
]
before = db.count_products()
db.upsert_products(junk, mode='refresh', updated_by='test')
check("both junk-SKU rows inserted separately", db.count_products() == before + 2,
      f"{before} -> {db.count_products()}")

if SCRAPE and SCRAPE.exists():
    print("\n== against the real CI scrape ==")
    DB.unlink(missing_ok=True)
    db._run_migrations_once.clear(); db.init_db()
    catalog.import_catalog_csv(pd.read_csv('storm_products_tagged.csv'), mode='add_new', updated_by='seed')
    base = db.count_products()

    incoming = catalog.rows_from_catalog_csv(pd.read_csv(SCRAPE))
    known = {str(p['product_url']) for p in db.get_products()}
    naive_new = len([r for r in incoming if r['product_url'] not in known])

    res = db.upsert_products(list(incoming), mode='refresh', updated_by='test')
    grew = db.count_products() - base
    print(f"   catalog {base} -> {db.count_products()}")
    print(f"   without SKU matching this would have added {naive_new} duplicates")
    print(f"   actually added: {grew}")
    check("SKU matching prevented the duplicate flood", grew < naive_new / 2,
          f"added {grew}, naive would add {naive_new}")
    check("catalog did not roughly double", db.count_products() < base * 1.5,
          f"{base} -> {db.count_products()}")

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
