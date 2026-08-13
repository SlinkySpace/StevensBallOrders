"""Guard tests for sync_catalog.py - the logic that stops an expired Storm
session from overwriting sponsor prices with retail prices."""
import os, sys
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(APP); sys.path.insert(0, APP)

from sync_catalog import evaluate_guards, parse_args

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

def rows(n, price=100.0, in_stock=True, start=0):
    return [{'product_url': f'u{i}', 'name': f'P{i}', 'price': price if in_stock else 0.0,
             'in_stock': in_stock} for i in range(start, start + n)]

def existing(n, price=100.0):
    return [{'product_url': f'u{i}', 'price': price} for i in range(n)]

args = parse_args([])
print(f"defaults: min_rows={args.min_rows} max_price_drift={args.max_price_drift} "
      f"max_out_of_stock={args.max_out_of_stock}\n")

print("== healthy scrape ==")
p, s = evaluate_guards(rows(426), existing(426), args)
check("clean scrape passes", p == [], str(p))
check("no drift reported", s['drift'] == 0.0)
check("compared every matched product", s['compared'] == 426)

print("\n== scrape broke partway ==")
p, s = evaluate_guards(rows(120), existing(426), args)
check("too-few-rows guard trips", any('usable rows' in x for x in p), str(p))

print("\n== session expired: retail prices everywhere ==")
# Logged out, Storm shows list price instead of the sponsor price.
retail = rows(426, price=189.99)
p, s = evaluate_guards(retail, existing(426, price=120.0), args)
check("price-drift guard trips", any('changed price' in x for x in p), str(p))
check("drift is 100%", abs(s['drift'] - 1.0) < 1e-9, f"drift={s['drift']}")
check("message warns about sponsor prices",
      any('sponsor prices' in x for x in p), str(p))

print("\n== session expired: no prices at all ==")
p, s = evaluate_guards(rows(426, in_stock=False), existing(426), args)
check("out-of-stock guard trips", any('no price' in x for x in p), str(p))
check("message points at the login", any('logged in' in x for x in p), str(p))

print("\n== out-of-stock rows must not count as price drift ==")
# A genuinely out-of-stock product reports price 0 and must be skipped, not
# counted as a change from its stored price.
mixed = rows(300) + rows(100, in_stock=False, start=300)
p, s = evaluate_guards(mixed, existing(400), args)
check("only priced rows compared", s['compared'] == 300, f"compared={s['compared']}")
check("no drift from the zero-price rows", s['drift'] == 0.0, f"drift={s['drift']}")
check("25% out of stock is under the 40% limit", p == [], str(p))

print("\n== a normal price update passes ==")
# Storm nudges 10% of the range.
mild = rows(400)
for r in mild[:40]:
    r['price'] = 110.0
p, s = evaluate_guards(mild, existing(400), args)
check("10% drift passes the 25% limit", p == [], str(p))
check("drift measured at 10%", abs(s['drift'] - 0.10) < 1e-9, f"drift={s['drift']}")

print("\n== drift right at the boundary ==")
boundary = rows(400)
for r in boundary[:100]:
    r['price'] = 110.0
p, s = evaluate_guards(boundary, existing(400), args)
check("exactly 25% does not trip (> not >=)", p == [], f"drift={s['drift']} {p}")
over = rows(400)
for r in over[:101]:
    r['price'] = 110.0
p, s = evaluate_guards(over, existing(400), args)
check("25.25% does trip", any('changed price' in x for x in p), str(p))

print("\n== float noise is not drift ==")
noisy = rows(400)
for r in noisy:
    r['price'] = 100.005
p, s = evaluate_guards(noisy, existing(400), args)
check("half-cent differences ignored", s['drift'] == 0.0, f"drift={s['drift']}")

print("\n== first run against an empty catalog ==")
p, s = evaluate_guards(rows(426), [], args)
check("no drift guard when there is nothing to compare", p == [], str(p))
check("all rows counted as new", s['new'] == 426, f"new={s['new']}")

print("\n== brand new products don't count as drift ==")
p, s = evaluate_guards(rows(450), existing(426), args)
check("24 new products detected", s['new'] == 24, f"new={s['new']}")
check("drift unaffected by new products", s['drift'] == 0.0)

print("\n== --force overrides (flag plumbed through) ==")
forced = parse_args(['--force'])
check("--force parsed", forced.force is True)
tuned = parse_args(['--max-price-drift', '0.6', '--min-rows', '10'])
half = rows(400)
for r in half[:200]:                      # a real 50% repricing
    r['price'] = 129.0
p, s = evaluate_guards(half, existing(400), tuned)
check("a raised threshold lets a real bulk change through", p == [],
      f"drift={s['drift']} {p}")
# ...but the same data still trips the default.
p_default, _ = evaluate_guards(half, existing(400), parse_args([]))
check("and the same data still trips the default limit",
      any('changed price' in x for x in p_default), str(p_default))

print("\n== dry-run and mode flags ==")
d = parse_args(['--dry-run', '--mode', 'add_new'])
check("--dry-run parsed", d.dry_run is True)
check("--mode parsed", d.mode == 'add_new')

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
