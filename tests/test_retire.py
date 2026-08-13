"""Retiring products Storm no longer lists."""
import os, sys, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "retire.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""
import db
db.DB_PATH = DB; db.USE_POSTGRES = False

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

db.init_db()

def product(url, name, sku='', in_stock=True):
    return {'product_url': url, 'sku': sku, 'name': name, 'price': 100.0,
            'in_stock': in_stock, 'is_visible': True, 'main_category': 'Equipment',
            'sub_category': 'Bowling Balls', 'product_type': 'bowling_ball',
            'scent': '', 'image_url': ''}

db.upsert_products([
    product('https://www.stormbowling.com/still-sold', 'STILL SOLD', 'AAA1'),
    product('https://www.stormbowling.com/discontinued', 'DISCONTINUED', 'BBB2'),
    product('https://www.stormbowling.com/already-oos', 'ALREADY OOS', 'CCC3', in_stock=False),
    product('club-shirt-2026', 'CLUB SHIRT', 'CLUB1'),          # added by hand
    product('raffle-prize', 'RAFFLE PRIZE', ''),                 # added by hand
], mode='refresh', updated_by='seed')
print(f"seeded {db.count_products()} products\n")

# A scrape that contains only the still-sold Storm product.
retired = db.retire_missing_products(
    ['https://www.stormbowling.com/still-sold'], updated_by='test')

names = sorted(r['name'] for r in retired)
check("retires the discontinued Storm product", 'DISCONTINUED' in names, str(names))
check("leaves the still-listed one alone", 'STILL SOLD' not in names, str(names))
check("does not re-retire something already out of stock", 'ALREADY OOS' not in names, str(names))
check("leaves hand-added club shirt alone", 'CLUB SHIRT' not in names, str(names))
check("leaves hand-added raffle prize alone", 'RAFFLE PRIZE' not in names, str(names))
check("retired exactly one", len(retired) == 1, str(names))

after = {p['name']: p for p in db.get_products()}
check("discontinued is now out of stock", not after['DISCONTINUED']['in_stock'])
check("discontinued was NOT deleted", 'DISCONTINUED' in after)
check("its price survived for when it returns", float(after['DISCONTINUED']['price']) == 100.0)
check("still-sold remains in stock", after['STILL SOLD']['in_stock'])
check("club shirt remains in stock", after['CLUB SHIRT']['in_stock'])
check("catalog size unchanged", len(after) == 5, str(len(after)))

# Re-running with the same scrape must not thrash.
again = db.retire_missing_products(['https://www.stormbowling.com/still-sold'], 'test')
check("second run retires nothing new", not again, str([r['name'] for r in again]))

# A product coming back should be restored by a normal upsert.
db.upsert_products([product('https://www.stormbowling.com/discontinued', 'DISCONTINUED', 'BBB2')],
                   mode='refresh', updated_by='test')
back = {p['name']: p for p in db.get_products()}['DISCONTINUED']
check("a returning product comes back in stock", back['in_stock'])

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
