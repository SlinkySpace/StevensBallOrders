"""replace as the default: the Storm catalog mirrors the file, hand-added items survive."""
import os, sys, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "replace.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""
import db
db.DB_PATH = DB; db.USE_POSTGRES = False
import sync_catalog

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

db.init_db()

def p(url, name, sku='', visible=True):
    return {'product_url': url, 'sku': sku, 'name': name, 'price': 100.0,
            'in_stock': True, 'is_visible': visible, 'main_category': 'Equipment',
            'sub_category': 'Bowling Balls', 'product_type': 'bowling_ball',
            'scent': '', 'image_url': ''}

print("== default mode ==")
check("sync_catalog defaults to replace", sync_catalog.parse_args([]).mode == 'replace',
      sync_catalog.parse_args([]).mode)

print("\n== replace clears Storm rows, keeps hand-added ==")
db.upsert_products([
    p('https://www.stormbowling.com/keeper', 'KEEPER', 'AAA1'),
    p('https://www.stormbowling.com/discontinued', 'DISCONTINUED', 'BBB2'),
    p('https://www.stormbowling.com/hidden-one', 'HIDDEN ONE', 'CCC3', visible=False),
    p('club-shirt-2026', 'CLUB SHIRT', 'CLUB1'),
    p('raffle-prize', 'RAFFLE PRIZE', ''),
], mode='refresh', updated_by='seed')
print(f"   seeded {len(db.get_products())}")

# The new scrape has KEEPER and the hidden product; DISCONTINUED is gone from Storm.
# Both arrive is_visible=True, as a scrape always does.
res = db.upsert_products([
    p('https://www.stormbowling.com/keeper', 'KEEPER', 'AAA1'),
    p('https://www.stormbowling.com/hidden-one', 'HIDDEN ONE', 'CCC3'),
], mode='replace', updated_by='sync')

after = {x['name']: x for x in db.get_products()}
check("discontinued Storm product is gone", 'DISCONTINUED' not in after, str(sorted(after)))
check("keeper survived", 'KEEPER' in after)
check("hand-added club shirt survived", 'CLUB SHIRT' in after)
check("hand-added raffle prize survived", 'RAFFLE PRIZE' in after)
check("catalog is now 4 rows", len(after) == 4, str(sorted(after)))
check("deleted count counts only Storm rows", res['deleted'] == 3, str(res))

print("\n== an admin's hidden flag survives replace ==")
check("hidden product is back but still hidden", not after['HIDDEN ONE']['is_visible'],
      "a scrape says visible; the admin said hidden and that must win")
check("keeper is visible", after['KEEPER']['is_visible'])
check("hidden product is not in the storefront listing",
      'HIDDEN ONE' not in {x['name'] for x in db.get_products(visible_only=True)})

print("\n== guards still gate replace ==")
args = sync_catalog.parse_args(['--mode', 'replace'])
rows = [{'product_url': f'https://www.stormbowling.com/p{i}', 'name': f'P{i}',
         'sku': f'S{i}', 'price': 10.0, 'in_stock': True} for i in range(50)]
existing = [{'product_url': f'https://www.stormbowling.com/p{i}', 'price': 10.0} for i in range(400)]
problems, _ = sync_catalog.evaluate_guards(rows, existing, args)
check("a truncated file is still blocked in replace mode",
      any('usable rows' in x for x in problems), str(problems))

healthy = [{'product_url': f'https://www.stormbowling.com/p{i}', 'name': f'P{i}',
            'sku': f'S{i}', 'price': 10.0, 'in_stock': True} for i in range(400)]
problems2, _ = sync_catalog.evaluate_guards(healthy, existing, args)
check("the new-products guard does not fire in replace mode",
      not any('look like new products' in x for x in problems2), str(problems2))

retail = [dict(r, price=r['price'] * 2.5) for r in healthy]
problems3, _ = sync_catalog.evaluate_guards(retail, existing, args)
check("a logged-out (retail price) scrape is still blocked in replace mode",
      any('changed price' in x for x in problems3), str(problems3))

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
