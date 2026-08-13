"""After dedupe, re-importing the same CSV must not resurrect the duplicates -
and repeating it must stay stable."""
import os, sys, tempfile
from pathlib import Path
from collections import Counter

APP = str(Path(__file__).resolve().parents[2])
OLD_CSV, NEW_CSV = Path(sys.argv[1]), Path(sys.argv[2])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "stable.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""
import db
db.DB_PATH = DB; db.USE_POSTGRES = False
import pandas as pd, catalog as C
import dedupe_products as D

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

db.init_db()

# 1. Rebuild production exactly: old catalog, then the bad run's import.
buggy = lambda u: (lambda t: t if t.isalnum() else '')(
    str(u or '').rstrip('/').split('/')[-1].split('-')[0].strip().upper())
original = C.sku_from_product_url
C.sku_from_product_url = buggy
C.import_catalog_csv(pd.read_csv(OLD_CSV), mode='add_new', updated_by='seed')
C.import_catalog_csv(pd.read_csv(NEW_CSV), mode='refresh', updated_by='scheduled refresh')
C.sku_from_product_url = original
print(f"production rebuild: {db.count_products()} products")

# 2. Dedupe, as the user just did.
D.main(['--local', '--yes'])
after_dedupe = db.count_products()
print(f"\nafter dedupe: {after_dedupe} products")

# 3. Re-import the very same CSV. This is the step that would undo the cleanup.
print("\nre-importing the same CSV:")
C.import_catalog_csv(pd.read_csv(NEW_CSV), mode='refresh', updated_by='repair')
after_reimport = db.count_products()
print(f"after re-import: {after_reimport} products")

check("re-import did not resurrect the duplicates",
      after_reimport <= after_dedupe + 5, f"{after_dedupe} -> {after_reimport}")

# 4. Do it again. A stable system converges.
C.import_catalog_csv(pd.read_csv(NEW_CSV), mode='refresh', updated_by='repair')
third = db.count_products()
check("a second re-import changes nothing", third == after_reimport,
      f"{after_reimport} -> {third}")

products = db.get_products()
dupes = [n for n, c in Counter(D.normalize_name(p['name']) for p in products).items() if c > 1]
check("no new duplicate names appeared", len(dupes) <= 3, str(dupes[:6]))

balls = [p for p in products if p['product_type'] == 'bowling_ball']
unknown = [p for p in products if p['sub_category'] in ('', 'Unknown')]
visible = [p for p in products if p['is_visible'] and p['in_stock']]
print(f"\nfinal state: {len(products)} products")
print(f"  bowling balls (get a weight selector): {len(balls)}")
print(f"  Unknown category:                     {len(unknown)}")
print(f"  visible to shoppers:                  {len(visible)}")
check("bowling balls are correctly typed", len(balls) >= 60, str(len(balls)))
check("categories recovered", len(unknown) <= 10, str(len(unknown)))

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
