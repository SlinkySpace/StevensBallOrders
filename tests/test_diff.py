import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(APP); sys.path.insert(0, APP)

import pandas as pd
from catalog_admin import _diff_rows, _editor_frame, EDITOR_COLUMNS

base = pd.DataFrame([
    {'product_url': 'u1', 'sku': 'A1', 'name': 'Ball One', 'price': 120.0,
     'in_stock': True, 'is_visible': True, 'main_category': 'Equipment',
     'sub_category': 'Bowling Balls', 'product_type': 'bowling_ball',
     'scent': '', 'image_url': 'static/catalog_images/a.webp'},
    {'product_url': 'u2', 'sku': 'B2', 'name': 'Towel', 'price': 10.0,
     'in_stock': True, 'is_visible': True, 'main_category': 'Equipment',
     'sub_category': 'Towels', 'product_type': 'general',
     'scent': '', 'image_url': ''},
    {'product_url': 'u3', 'sku': 'C3', 'name': 'Shirt', 'price': 25.0,
     'in_stock': False, 'is_visible': True, 'main_category': 'Merchandise',
     'sub_category': 'Apparel', 'product_type': 'apparel',
     'scent': '', 'image_url': ''},
])

original = _editor_frame(base)

def check(label, mutate, expected):
    edited = original.copy()
    mutate(edited)
    got = _diff_rows(original, edited)
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"      expected {expected}")
        print(f"      got      {got}")
    return ok

results = []

results.append(check("no edits -> no updates", lambda d: None, []))

results.append(check(
    "price edit",
    lambda d: d.__setitem__('price', [130.0, 10.0, 25.0]),
    [{'price': 130.0, 'product_url': 'u1'}]))

results.append(check(
    "float noise below a cent is ignored",
    lambda d: d.__setitem__('price', [120.0001, 10.0, 25.0]),
    []))

results.append(check(
    "untick in_stock",
    lambda d: d.__setitem__('in_stock', [False, True, False]),
    [{'in_stock': False, 'product_url': 'u1'}]))

results.append(check(
    "untick is_visible",
    lambda d: d.__setitem__('is_visible', [True, False, True]),
    [{'is_visible': False, 'product_url': 'u2'}]))

results.append(check(
    "rename",
    lambda d: d.__setitem__('name', ['Ball One', 'Micro Towel', 'Shirt']),
    [{'name': 'Micro Towel', 'product_url': 'u2'}]))

results.append(check(
    "category + type change on one row",
    lambda d: (d.__setitem__('sub_category', ['Bowling Balls', 'Towels', 'Accessories']),
               d.__setitem__('product_type', ['bowling_ball', 'general', 'general'])),
    [{'sub_category': 'Accessories', 'product_type': 'general', 'product_url': 'u3'}]))

results.append(check(
    "multiple rows at once",
    lambda d: (d.__setitem__('price', [130.0, 12.0, 25.0]),
               d.__setitem__('in_stock', [True, True, True])),
    [{'price': 130.0, 'product_url': 'u1'},
     {'price': 12.0, 'product_url': 'u2'},
     {'in_stock': True, 'product_url': 'u3'}]))

# image_url / product_url are disabled in the editor and must never be emitted.
edited = original.copy()
edited['image_url'] = ['zzz', 'zzz', 'zzz']
emitted_keys = {k for u in _diff_rows(original, edited) for k in u}
ok = 'image_url' not in emitted_keys
print(f"{'PASS' if ok else 'FAIL'}  disabled image_url column never emitted")
results.append(ok)

# A filtered subset still diffs correctly (indexes are reset).
subset = _editor_frame(base[base['sub_category'] == 'Apparel'])
sub_edit = subset.copy()
sub_edit['price'] = [30.0]
got = _diff_rows(subset, sub_edit)
ok = got == [{'price': 30.0, 'product_url': 'u3'}]
print(f"{'PASS' if ok else 'FAIL'}  filtered subset diffs against the right row")
if not ok:
    print("      got", got)
results.append(ok)

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
