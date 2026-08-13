"""Dedupe tool, tested against a rebuild of the real production state."""
import os, sys, tempfile
from pathlib import Path
from collections import Counter

APP = str(Path(__file__).resolve().parents[2])
OLD_CSV, NEW_CSV = Path(sys.argv[1]), Path(sys.argv[2])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "dedupe_test.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""
import db
db.DB_PATH = DB; db.USE_POSTGRES = False
import pandas as pd, catalog
from dedupe_products import find_duplicates, normalize_name, score, is_junk

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

print("== name normalisation ==")
check("case and punctuation collapse",
      normalize_name('!Q TOUR 78/U') == normalize_name('!q  tour 78 u'))
check("distinct products stay distinct",
      normalize_name('ION PRO') != normalize_name('ION PRO SOLID'))
check("empty stays empty", normalize_name('') == '')

print("\n== keeper preference ==")
a = {'id': 5, 'sku': 'BBMVLL', 'name': 'X', 'price': 1, 'image_url': '', 'updated_by': 'scheduled refresh'}
b = {'id': 9, 'sku': '',       'name': 'X', 'price': 1, 'image_url': '', 'updated_by': 'scheduled refresh'}
check("a real SKU beats a blank one", score(a) > score(b))
c = {'id': 20, 'sku': '', 'name': 'X', 'price': 1, 'image_url': '', 'updated_by': 'jela@stevens.edu'}
check("a hand-edited row beats an untouched one", score(c) > score(b))
d = {'id': 2, 'sku': 'AAA', 'name': 'X', 'price': 1, 'image_url': '', 'updated_by': 'scheduled refresh'}
check("otherwise the older row wins", score(d) > score(a))

print("\n== against the rebuilt production state ==")
db.init_db()
catalog.import_catalog_csv(pd.read_csv(OLD_CSV), mode='add_new', updated_by='seed')

# The fixed pipeline refuses to create this mess - it drops query-string URLs and
# no longer invents SKUs - so inject it directly, the way the bad run left the
# database, and check the cleanup still recognises it.
mess = []
for i, (name, sku, url) in enumerate([
    ('!Q TOUR 78/U', 'STORM', 'https://www.stormbowling.com/storm-iq-tour-78u-bowling-ball'),
    ('HUSTLE EARTH', 'ROTO', 'https://www.stormbowling.com/roto-grip-hustle-bowling-ball-earth'),
    ('SPEED-PLUG KIT', 'MASTER', 'https://www.stormbowling.com/master-speed-plug-kit'),
]):
    mess.append({'product_url': url, 'sku': sku, 'name': name, 'price': 0.0,
                 'in_stock': False, 'is_visible': True, 'main_category': 'Unknown',
                 'sub_category': 'Unknown', 'product_type': 'general',
                 'scent': '', 'image_url': ''})
for i in range(5):   # ball-compare junk
    mess.append({'product_url': f'https://www.stormbowling.com/ball-compare?item1=BB{i}',
                 'sku': '', 'name': 'Company', 'price': 0.0, 'in_stock': False,
                 'is_visible': True, 'main_category': 'Unknown', 'sub_category': 'Unknown',
                 'product_type': 'general', 'scent': '', 'image_url': ''})
db.upsert_products(mess, mode='refresh', updated_by='bad run')

products = db.get_products()
before = len(products)
dupes, ambiguous = find_duplicates(products)
junk = [p for p in products if is_junk(p)]
losers = [p for _, extra in dupes for p in extra] + junk
print(f"   {before} products, {len(dupes)} mergeable, {len(junk)} junk, {len(ambiguous)} ambiguous, {len(losers)} to drop")

# With the pipeline fixed, an import can no longer create these - name matching
# re-keys them onto the existing row - so exercise the merge logic directly.
synthetic = [
    {'id': 1, 'name': '!Q TOUR 78/U', 'sku': 'BBMVLL', 'price': 110.0, 'image_url': '',
     'updated_by': 'seed',
     'product_url': 'https://www.stormbowling.com/products/equipment/bowling-balls/bbmvll-q-tour-78u'},
    {'id': 2, 'name': '!Q Tour 78/U', 'sku': 'STORM', 'price': 0.0, 'image_url': '',
     'updated_by': 'bad run',
     'product_url': 'https://www.stormbowling.com/storm-iq-tour-78u-bowling-ball'},
]
syn_merge, syn_amb = find_duplicates(synthetic)
check("merges a real row with its invented-SKU twin", len(syn_merge) == 1, str(syn_merge))
if syn_merge:
    keeper, dropped = syn_merge[0]
    check("keeps the row with the genuine SKU", keeper['sku'] == 'BBMVLL', keeper['sku'])
    check("drops the invented-SKU row", dropped[0]['sku'] == 'STORM', str(dropped))
check("no false ambiguity from an invented SKU", not syn_amb, str(syn_amb))

check("import-time matching now prevents new duplicates", len(dupes) == 0, str(len(dupes)))
keepers = {k['product_url'] for k, _ in dupes}
check("never drops a row it also keeps",
      not (keepers & {p['product_url'] for p in losers}))
with_sku = [p for p in losers if str(p['sku'] or '').strip()]
print(f"   rows dropped that still had a SKU: {len(with_sku)}")

db.delete_products([p['product_url'] for p in losers])
after = db.get_products()
print(f"   after dedupe: {len(after)} products")
check("count dropped by exactly the loser count", len(after) == before - len(losers))
remaining = {n for n, c in Counter(normalize_name(p['name']) for p in after).items() if c > 1}
# The only names still appearing twice should be the ones deliberately left
# alone because their SKUs differ, i.e. genuinely distinct products.
expected = {normalize_name(m[0]['name']) for m in ambiguous}
check("only the deliberately-kept groups still share a name",
      remaining == expected, f"remaining={sorted(remaining)} expected={sorted(expected)}")

balls = [p for p in after if p['product_type'] == 'bowling_ball']
unknown = [p for p in after if p['sub_category'] in ('', 'Unknown')]
print(f"\n   final: {len(after)} products, {len(balls)} bowling balls, {len(unknown)} Unknown category")
check("bowling balls survived dedupe", len(balls) >= 60, str(len(balls)))
check("same-name-different-SKU groups were left alone", len(ambiguous) >= 1, str(len(ambiguous)))
check("ball-compare junk detected", len(junk) > 0, str(len(junk)))

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
