"""The product-URL filter that replaced the absolute XPath, tested against the
real link shapes seen on stormbowling.com listing pages."""
import os, sys, re
from urllib.parse import urlparse

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(APP); sys.path.insert(0, APP)

NON_PRODUCT_ROOTS = {
    'products','company','events','community','cart','account','login','register',
    'logout','search','contact','about','news','blog','dealers','sitemap',
    'privacy-policy','terms-of-use','terms-and-conditions','terms-of-service',
    'shipping-policy','return-policy','my-account','order-history','contact-us',
    'about-us','where-to-buy','find-a-dealer','customer-service',
}


PAGE_HOST = 'www.stormbowling.com'


def _bare(host: str) -> str:
    return (host or '').replace('www.', '', 1).lower()


# Mirror of the isProduct() predicate inside EXTRACT_LISTING_ITEMS_JS.
def is_product(href: str) -> bool:
    if not href:
        return False

    absolute = href if '://' in href or ':' in href.split('/')[0] else f'https://{PAGE_HOST}{href}'
    try:
        u = urlparse(absolute)
    except ValueError:
        return False

    if u.scheme not in ('http', 'https'):
        return False
    if _bare(u.hostname or PAGE_HOST) != _bare(PAGE_HOST):
        return False

    parts = [p for p in u.path.split('/') if p]
    if not parts:
        return False
    if parts[0] == 'products':
        return len(parts) >= 4 and not re.fullmatch(r'\d+', parts[1])

    slug = parts[0].lower()
    return (len(parts) == 1 and re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug) is not None
            and '-' in slug and slug not in NON_PRODUCT_ROOTS)

SHOULD_MATCH = [
    'https://www.stormbowling.com/products/equipment/bowling-balls/bbmveq-equinox',
    'https://www.stormbowling.com/products/merchandise/apparel/shst195-storm-nation-tee-red',
    'https://www.stormbowling.com/products/equipment/shoe-accessories/sp-sl-3g-shoe-slider',
    '/products/bowling-essentials/cleaners-polishes/power_edge-power-edge',
    'https://www.stormbowling.com/products/equipment/bowling-bags/37137-rt-3-ball-signature-ptlp',
    # Root-level products, which the first version of this filter dropped.
    'https://www.stormbowling.com/900-global-3-ball-deluxe-roller',
    'https://www.stormbowling.com/stormopoly-bowling-board-game',
    '/storm-power-glove-throttle',
]
SHOULD_NOT_MATCH = [
    # The link that actually crashed the run: tel: parses to a pathname of
    # "(435)-723-0403" - one segment, contains a hyphen.
    'tel:(435)-723-0403',
    'tel:435-723-0403',
    'mailto:sales@stormbowling.com',
    'javascript:void(0)',
    '#some-anchor',
    'https://www.facebook.com/storm-bowling',      # off-site
    'https://shop.other-site.com/some-product',
    'https://www.stormbowling.com/company',
    'https://www.stormbowling.com/events',
    'https://www.stormbowling.com/privacy-policy',
    'https://www.stormbowling.com/where-to-buy',
    'https://www.stormbowling.com/contact-us',
    'https://www.stormbowling.com/products/24/1/1/',        # the paged listing itself
    'https://www.stormbowling.com/products/24/1/12/',
    'https://www.stormbowling.com/products/equipment/',      # category
    'https://www.stormbowling.com/products/bowling-essentials/',
    'https://www.stormbowling.com/products/equipment/grip-aids/',   # sub-category
    'https://www.stormbowling.com/company/about',
    'https://www.stormbowling.com/',
    '', None,
]

ok = True
print("should be treated as products:")
for u in SHOULD_MATCH:
    good = is_product(u)
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {u}")

print("\nshould be ignored:")
for u in SHOULD_NOT_MATCH:
    good = not is_product(u)
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {u!r}")

# The real catalog: every product_url we already have must pass.
import pandas as pd
df = pd.read_csv('storm_products_tagged.csv')
missed = [u for u in df['product_url'] if not is_product(u)]
print(f"\nagainst the live catalog: {len(df) - len(missed)}/{len(df)} recognised")
if missed:
    ok = False
    for u in missed[:5]:
        print(f"  MISSED {u}")

print("\nALL PASS" if ok else "\nFAILURES")
sys.exit(0 if ok else 1)
