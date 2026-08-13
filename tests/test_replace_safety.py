"""The gaps the audit found in replace mode: preservation, delete bound, drift coverage."""
import os, sys, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "replace_safety.db"
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

S = 'https://www.stormbowling.com'

def p(url, name, sku='', price=100.0, cat='Equipment', sub='Bowling Balls',
      ptype='bowling_ball', img='static/x.webp', visible=True):
    return {'product_url': url, 'sku': sku, 'name': name, 'price': price,
            'in_stock': price > 0, 'is_visible': visible, 'main_category': cat,
            'sub_category': sub, 'product_type': ptype, 'scent': '', 'image_url': img}

print("== a scrape that lost fields must not overwrite good stored data ==")
db.upsert_products([
    p(f'{S}/products/equipment/bowling-balls/phaze', 'PHAZE II', 'BB1',
      price=189.99, cat='Equipment', sub='Bowling Balls', ptype='bowling_ball',
      img='static/phaze.webp'),
    p(f'{S}/products/equipment/bowling-balls/hidden', 'HIDDEN BALL', 'BB2',
      price=150.0, visible=False),
], mode='refresh', updated_by='seed')

# Same products, new root-level URLs, and the detail page timed out: no price,
# no image, no category, generic type.
db.upsert_products([
    p(f'{S}/storm-phaze-ii', 'PHAZE II', 'BB1', price=0.0, cat='Unknown',
      sub='Unknown', ptype='general', img=''),
    p(f'{S}/storm-hidden-ball', 'HIDDEN BALL', 'BB2', price=0.0, cat='Unknown',
      sub='Unknown', ptype='general', img=''),
], mode='replace', updated_by='sync')

after = {x['name']: x for x in db.get_products()}
phaze = after.get('PHAZE II', {})
check("stored price survives a scrape that reported 0", float(phaze.get('price', 0)) == 189.99,
      f"got {phaze.get('price')}")
check("stored image survives a blank scrape", phaze.get('image_url') == 'static/phaze.webp',
      f"got {phaze.get('image_url')!r}")
check("stored category survives an Unknown scrape", phaze.get('main_category') == 'Equipment',
      f"got {phaze.get('main_category')!r}")
check("stored sub-category survives", phaze.get('sub_category') == 'Bowling Balls',
      f"got {phaze.get('sub_category')!r}")
check("product_type survives a 'general' scrape", phaze.get('product_type') == 'bowling_ball',
      f"got {phaze.get('product_type')!r}  (this one decides the weight selector)")
check("the row did adopt Storm's new URL", phaze.get('product_url') == f'{S}/storm-phaze-ii',
      f"got {phaze.get('product_url')!r}")
check("hidden flag carried across the URL move",
      not after.get('HIDDEN BALL', {}).get('is_visible', True))

print("\n== a real price still overwrites ==")
db.upsert_products([p(f'{S}/storm-phaze-ii', 'PHAZE II', 'BB1', price=175.5,
                      cat='Equipment', sub='Bowling Balls', img='static/new.webp')],
                   mode='replace', updated_by='sync')
phaze = {x['name']: x for x in db.get_products()}['PHAZE II']
check("a genuine new price is applied", float(phaze['price']) == 175.5, str(phaze['price']))
check("a genuine new image is applied", phaze['image_url'] == 'static/new.webp')

print("\n== the deletion bound ==")
existing = [{'product_url': f'{S}/p{i}', 'price': 10.0, 'sku': f'S{i}',
             'name': f'P{i}', 'in_stock': True} for i in range(400)]

def rows_for(n, price=10.0):
    return [{'product_url': f'{S}/p{i}', 'name': f'P{i}', 'sku': f'S{i}',
             'price': price, 'in_stock': True} for i in range(n)]

args = sync_catalog.parse_args(['--mode', 'replace'])
problems, stats = sync_catalog.evaluate_guards(rows_for(340), existing, args)
check("a 340-of-400 file is blocked (would delete 15%)",
      any('deleted outright' in x for x in problems), str(problems))

problems, _ = sync_catalog.evaluate_guards(rows_for(395), existing, args)
check("a 395-of-400 file passes (1% delisted is normal)",
      not any('deleted outright' in x for x in problems), str(problems))

problems, _ = sync_catalog.evaluate_guards(rows_for(340), existing,
                                           sync_catalog.parse_args(['--mode', 'refresh']))
check("the delete bound does not apply to refresh mode",
      not any('deleted outright' in x for x in problems), str(problems))

print("\n== the drift-coverage guard ==")
# Same products, but every URL moved and nothing was re-keyed: drift sees nothing.
moved = [{'product_url': f'{S}/moved-{i}', 'name': f'P{i}', 'sku': f'S{i}',
          'price': 10.0, 'in_stock': True} for i in range(400)]
problems, stats = sync_catalog.evaluate_guards(moved, existing, args)
check("a file that matched almost nothing is blocked, not passed as 0% drift",
      any('price compared' in x for x in problems), str(problems))
check("...and it reports 0 comparisons", stats['compared'] == 0, str(stats['compared']))

problems, stats = sync_catalog.evaluate_guards(rows_for(400), existing, args)
check("full coverage passes cleanly", not problems, str(problems))
check("...having compared everything", stats['compared'] == 400, str(stats['compared']))

print("\n== a retail-price scrape is still caught ==")
problems, _ = sync_catalog.evaluate_guards(rows_for(400, price=25.0), existing, args)
check("2.5x prices trip the drift guard", any('changed price' in x for x in problems), str(problems))

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
