import csv
import os
import re
import sys
import time
from collections import Counter
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BASE_DOMAIN = "https://www.stormbowling.com"
START_PAGE = int(os.environ.get("SCRAPER_START_PAGE", 1))
END_PAGE = int(os.environ.get("SCRAPER_END_PAGE", 19))
OUTPUT_CSV = "storm_products.csv"
AUTH_STATE_FILE = os.environ.get("STORM_AUTH_STATE_FILE", "storm_auth_state.json")

# First run:
#   SETUP_LOGIN = True
#   HEADLESS_SCRAPE = False
#
# After auth state is saved:
#   SETUP_LOGIN = False
#   HEADLESS_SCRAPE = True
SETUP_LOGIN = _env_flag("SCRAPER_SETUP_LOGIN", False)
HEADLESS_SCRAPE = _env_flag("SCRAPER_HEADLESS", True)

# True = use installed Microsoft Edge channel
# False = use bundled Chromium
#
# CI runners have no Edge, so the workflow sets SCRAPER_USE_EDGE=false to fall
# back to the Chromium that `playwright install` provides.
USE_EDGE_CHANNEL = _env_flag("SCRAPER_USE_EDGE", True)

LISTING_URL_TEMPLATE = "https://www.stormbowling.com/products/24/1/{page}/"

# Walking the category tree instead of the numbered listing pages. Each
# sub-category page states what it holds, so main/sub category come from the URL
# we asked for rather than being guessed from a product slug afterwards - which
# is what left 79 products filed under Unknown.
#
# per_page asks for the whole category in one response, so a category is one
# request rather than several, which also means less throttling.
CATEGORY_ROOTS = [
    "https://www.stormbowling.com/products/equipment/",
    "https://www.stormbowling.com/products/bowling-essentials/",
    "https://www.stormbowling.com/products/merchandise/",
]
CATEGORY_PAGE_SIZE = 200
USE_CATEGORY_WALK = _env_flag("SCRAPER_CATEGORY_WALK", True)

# Listing page
LIST_CONTAINER_XPATH = "/html/body/div[3]/div/div/div/div[2]/div[2]/div/div[3]/div/div/div/div/div[1]/form/ul"

# Detail page
NAME_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[1]/div/div[1]/div/h1"

# Use the full h4 text, not the span label itself
SKU_H4_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[1]/div/div[1]/div/h4"
SKU_LABEL_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[1]/div/div[1]/div/h4/span"

PRICE_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[1]/div/div[2]/div/div/div/span"

# Scent / fragrance
SCENT_P_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[2]/div/div[2]/div/p[15]"
SCENT_STRONG_XPATH = "/html/body/div[2]/div[1]/div/div/div/div[2]/div[2]/form/div[2]/div[2]/div[1]/div/div/div/div[2]/div/div[2]/div/p[15]/strong"

LOADER_IMAGE_FRAGMENTS = [
    "ajax-loader.gif",
    "loader.gif",
    "loading.gif",
    "spinner"
]

# A real product photo always sits under the product's own thumbnail path:
#   /contents/<SKU>/thumbnail/big_AC574RD@1.png
#
# Anything else is a site asset. Blocklisting those folders one at a time was a
# losing game - rejecting /ckfinder/images/ simply moved the fallback on to
# /contents/global/storm-blk-logo.jpeg - so this matches the real thing instead.
#
# Measured over two full scrapes, 726 rows: every one of the 363 genuine photos
# contains /thumbnail/, no /thumbnail/ URL is ever shared between products, and
# every URL without it was a logo reused 5 to 61 times.
PRODUCT_IMAGE_MARKER = "/thumbnail/"

# If the marker ever stops appearing, images vanish rather than going wrong, and
# this threshold makes the run say so instead of quietly shipping a blank
# catalog.
MIN_EXPECTED_IMAGE_RATIO = 0.40

# A picture shared by this many products is a stand-in whatever its path.
PLACEHOLDER_REUSE_LIMIT = 3


def clean_text(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def text_or_empty(locator) -> str:
    try:
        if locator.count() == 0:
            return ""
        value = locator.first.text_content(timeout=3000)
        return clean_text(value or "")
    except Exception:
        return ""


def attr_or_empty(locator, attr_name: str) -> str:
    try:
        if locator.count() == 0:
            return ""
        value = locator.first.get_attribute(attr_name, timeout=2000)
        return value.strip() if value else ""
    except Exception:
        return ""


def is_loader_image(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return any(fragment in lowered for fragment in LOADER_IMAGE_FRAGMENTS)


def is_product_image(url: str) -> bool:
    """True only for a picture of the product itself, not a spinner or a logo."""
    if is_loader_image(url):
        return False
    return PRODUCT_IMAGE_MARKER in str(url).lower()


def is_placeholder_image(url: str) -> bool:
    """Anything that is not a photo of the product."""
    return not is_product_image(url)


def extract_best_image_url(img_locator) -> str:
    """
    Prefer a real image URL over any loading gif / spinner.
    Checks several common lazy-load attributes.
    """
    try:
        if img_locator.count() == 0:
            return ""

        attrs_to_check = [
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "srcset",
            "data-srcset",
        ]

        candidates = []

        for attr in attrs_to_check:
            val = attr_or_empty(img_locator, attr)
            if not val:
                continue

            if "srcset" in attr:
                parts = [p.strip() for p in val.split(",") if p.strip()]
                for part in parts:
                    url_part = part.split()[0].strip()
                    if url_part:
                        candidates.append(url_part)
            else:
                candidates.append(val)

        # First pass: return first non-loader candidate
        for candidate in candidates:
            if candidate and not is_loader_image(candidate):
                return candidate

        return ""
    except Exception:
        return ""


# Pulls every product-detail link on a listing page, with the best image it can
# find nearby.
#
# Two shapes exist. Most products sit at /products/<main>/<sub>/<slug>, but a
# handful (the 900 Global bags, Stormopoly) live at the site root as a single
# hyphenated slug, so both are accepted and known non-product roots are excluded.
# Erring towards including a link is cheap: the detail page then yields no name,
# and rows without a name are dropped when the CSV is imported.
#
# This replaced an absolute XPath (/html/body/div[3]/div/...) which broke the
# moment anything shifted the DOM - the cookie consent banner alone was enough.
EXTRACT_LISTING_ITEMS_JS = """
() => {
  // A container needs at least this many link-plus-image cells to count as the
  // product grid, which keeps small image menus from being mistaken for it.
  const MIN_GRID_CELLS = 4;

  const NON_PRODUCT_ROOTS = new Set([
    'products','company','events','community','cart','account','login','register',
    'logout','search','contact','about','news','blog','dealers','sitemap',
    'privacy-policy','terms-of-use','terms-and-conditions','terms-of-service',
    'shipping-policy','return-policy','my-account','order-history','contact-us',
    'about-us','where-to-buy','find-a-dealer','customer-service',
    'ball-compare','ball-motion','ball-guide','storm-youth-championships',
    'about-storm-products','storm-nation-newsletter'
  ]);

  const bareHost = (h) => (h || '').replace(/^www\\./, '').toLowerCase();

  const partsOf = (href) => {
    if (!href) return null;
    let url;
    try { url = new URL(href, location.origin); } catch (e) { return null; }
    // Without these two checks "tel:(435)-723-0403" parses to a pathname of
    // "(435)-723-0403", which the root-slug rule below happily accepted - and
    // the scraper then tried to navigate to it.
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (bareHost(url.hostname) !== bareHost(location.hostname)) return null;
    // Product pages are addressed by path alone. The ball comparison tool links
    // out as /ball-compare?item1=BBMVXA once per ball, and each distinct query
    // string looked like a separate product - 61 of them were scraped, all
    // titled "Company".
    if (url.search) return null;
    const parts = url.pathname.split('/').filter(Boolean);
    return parts.length ? parts : null;
  };

  // Unambiguous: /products/<main>/<sub>/<slug>. Used to find the grid.
  const isCatalogPath = (href) => {
    const parts = partsOf(href);
    return !!parts && parts[0] === 'products' && parts.length >= 4 && !/^\\d+$/.test(parts[1]);
  };

  // Root-level product, e.g. /900-global-2-ball-deluxe-tote. Only trusted
  // inside the grid, since most single hyphenated slugs are content pages.
  const isRootProduct = (href) => {
    const parts = partsOf(href);
    if (!parts || parts.length !== 1) return false;
    const slug = parts[0].toLowerCase();
    return /^[a-z0-9][a-z0-9-]*$/.test(slug)
        && slug.includes('-')
        && !NON_PRODUCT_ROOTS.has(slug);
  };

  const isProduct = (href) => isCatalogPath(href) || isRootProduct(href);

  const pickImage = (scope) => {
    for (const img of scope.querySelectorAll('img')) {
      for (const attr of ['data-src', 'data-lazy-src', 'data-original', 'src']) {
        const v = img.getAttribute(attr);
        if (v && !/ajax-loader|loading\\.gif|loader\\.gif|spinner/i.test(v)) return v;
      }
      const srcset = img.getAttribute('srcset') || img.getAttribute('data-srcset');
      if (srcset) {
        const first = srcset.split(',')[0].trim().split(/\\s+/)[0];
        if (first) return first;
      }
    }
    return '';
  };

  // Finding the grid by its /products/ links failed on whole categories: every
  // bowling ball has moved to a root-level URL, so those listing pages contain
  // no /products/<main>/<sub>/<slug> link at all, no grid was recognised, and
  // the page came back empty. Ten of nineteen pages, and every ball, were lost.
  //
  // Identify it by shape instead. A product card is a link with a thumbnail;
  // navigation and footer links are not. Whichever container holds the most
  // link-plus-image cells is the grid, whatever the URLs inside it look like.
  const anchors = [...document.querySelectorAll('a[href]')];
  const strict = anchors.filter(a => isCatalogPath(a.getAttribute('href')));

  const tally = new Map();
  for (const a of anchors) {
    const cell = a.closest('li') || a.parentElement;
    if (!cell || !cell.querySelector('img')) continue;
    const container = cell.parentElement;
    if (!container) continue;
    const seen = tally.get(container) || { cells: new Set(), products: 0 };
    seen.cells.add(cell);
    if (isProduct(a.getAttribute('href'))) seen.products += 1;
    tally.set(container, seen);
  }

  // Prefer the container holding the most product links, then the most cards,
  // so a small image-bearing menu cannot outrank the real grid.
  const ranked = [...tally.entries()]
    .filter(([, v]) => v.cells.size >= MIN_GRID_CELLS && v.products > 0)
    .sort((x, y) => (y[1].products - x[1].products) || (y[1].cells.size - x[1].cells.size));
  const grid = ranked.length ? ranked[0][0] : null;

  // Without a recognisable grid, take only the unambiguous links so navigation
  // can never leak in.
  const candidates = grid
    ? [...grid.querySelectorAll('a[href]')].filter(a => isProduct(a.getAttribute('href')))
    : strict;

  const seen = new Set();
  const out = [];
  for (const a of candidates) {
    const abs = new URL(a.getAttribute('href'), location.origin).href;
    if (seen.has(abs)) continue;
    seen.add(abs);
    // Climb to the enclosing card so the image lookup has somewhere to search.
    const card = a.closest('li') || a.parentElement || a;
    out.push({ product_url: abs, image_url: pickImage(card) || pickImage(a) });
  }
  return out;
}
"""

LOGGED_OUT_MARKERS = ('register', 'login', 'sign in')

# How many times to re-read a listing page before accepting that it is empty.
LISTING_ATTEMPTS = 3


def dismiss_cookie_banner(page) -> None:
    """
    The consent banner overlays the page and adds a div near the top of <body>.
    Decline non-essential cookies, and settle for hiding it if no button matches.
    """
    for label in ('Deny', 'Decline', 'Reject all', 'Only necessary'):
        try:
            button = page.get_by_role('button', name=label, exact=False)
            if button.count() > 0:
                button.first.click(timeout=2500)
                page.wait_for_timeout(400)
                return
        except Exception:
            continue

    # No recognisable button: drop any fixed overlay so it can't intercept clicks.
    try:
        page.evaluate("""
            () => {
              for (const el of document.querySelectorAll('div,section,aside')) {
                const t = (el.innerText || '').toLowerCase();
                if (t.includes('this website uses cookies') && el.offsetParent !== null) {
                  el.style.display = 'none';
                }
              }
            }
        """)
    except Exception:
        pass


def looks_logged_out(page) -> bool:
    """
    Storm only renders the dealer catalog to a signed-in account. A logged-out
    scrape silently yields nothing (or retail pricing), so detect it explicitly.
    """
    try:
        header = (page.inner_text('body', timeout=5000) or '')[:4000].lower()
    except Exception:
        return False

    has_login_prompt = any(marker in header for marker in LOGGED_OUT_MARKERS)
    has_account_hint = any(word in header for word in ('logout', 'log out', 'my account', 'sign out'))
    return has_login_prompt and not has_account_hint


def _title_case(slug: str) -> str:
    """bowling-balls -> Bowling Balls"""
    return " ".join(word.capitalize() for word in str(slug).split("-") if word)


def discover_category_pages(page) -> list[dict]:
    """
    Find every sub-category listing, e.g. /products/equipment/bowling-balls/.

    Discovered rather than hard-coded, so a category Storm adds is picked up
    without a code change.
    """
    found: dict[str, dict] = {}

    for root in CATEGORY_ROOTS:
        try:
            page.goto(root, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(900)
            dismiss_cookie_banner(page)
        except Exception as exc:
            print(f"[WARN] Could not open {root}: {exc}")
            continue

        try:
            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))"
            ) or []
        except Exception:
            hrefs = []

        for href in hrefs:
            if not href:
                continue
            try:
                path = urlparse(urljoin(BASE_DOMAIN, href)).path
            except ValueError:
                continue
            parts = [p for p in path.split("/") if p]
            # /products/<main>/<sub>/ and nothing deeper
            if len(parts) != 3 or parts[0] != "products":
                continue

            url = f"{BASE_DOMAIN}/products/{parts[1]}/{parts[2]}/"
            found.setdefault(url, {
                "url": url,
                "main_category": _title_case(parts[1]),
                "sub_category": _title_case(parts[2]),
            })

    categories = sorted(found.values(), key=lambda c: (c["main_category"], c["sub_category"]))
    print(f"[INFO] Found {len(categories)} sub-categories")
    return categories


def scroll_listing_page(page):
    """
    Scroll through the page to trigger lazy-loaded thumbnails.
    """
    last_height = -1
    same_count = 0

    while True:
        height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)

        if height == last_height:
            same_count += 1
        else:
            same_count = 0

        if same_count >= 2:
            break

        last_height = height

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(700)


def save_auth_state():
    with sync_playwright() as p:
        browser_type = p.chromium
        launch_kwargs = {"headless": False}
        if USE_EDGE_CHANNEL:
            launch_kwargs["channel"] = "msedge"

        browser = browser_type.launch(**launch_kwargs)
        context = browser.new_context()
        page = context.new_page()

        page.goto(BASE_DOMAIN, wait_until="domcontentloaded")
        print("\nLog in manually in the opened browser.")
        print("Once you are fully logged in and can access the product pages, return here.")
        input("Press Enter to save auth state and close the browser... ")

        context.storage_state(path=AUTH_STATE_FILE, indexed_db=True)
        browser.close()

    print(f"Saved auth state to {AUTH_STATE_FILE}")


def open_browser_context(playwright):
    if not os.path.exists(AUTH_STATE_FILE):
        raise FileNotFoundError(
            f"{AUTH_STATE_FILE} not found. Run once with SETUP_LOGIN = True first."
        )

    browser_type = playwright.chromium
    launch_kwargs = {"headless": HEADLESS_SCRAPE}
    if USE_EDGE_CHANNEL:
        launch_kwargs["channel"] = "msedge"

    browser = browser_type.launch(**launch_kwargs)
    context = browser.new_context(storage_state=AUTH_STATE_FILE)
    return browser, context


def collect_listing_items(page, listing_url: str):
    page.goto(listing_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)

    dismiss_cookie_banner(page)

    # The grid arrives after the initial HTML. Reading too early returned
    # nothing for half the listing pages on one run - 241 products instead of
    # 426 - so retry, scrolling between attempts to nudge lazy loading, and
    # only conclude a page is empty once it has had several chances.
    found = []
    for attempt in range(LISTING_ATTEMPTS):
        try:
            page.wait_for_selector("a[href*='/products/']", timeout=8000)
        except Exception:
            pass

        scroll_listing_page(page)
        page.wait_for_timeout(900)

        try:
            found = page.evaluate(EXTRACT_LISTING_ITEMS_JS)
        except Exception as exc:
            print(f"[WARN] Could not read products from {listing_url}: {exc}")
            found = []

        if found:
            break
        if attempt < LISTING_ATTEMPTS - 1:
            print(f"[INFO] Nothing yet on {listing_url}, retrying "
                  f"({attempt + 2}/{LISTING_ATTEMPTS})")
            page.wait_for_timeout(2000)

    if not found:
        print(f"[INFO] No products found on {listing_url}")
        return []

    results = []
    for entry in found:
        image = str(entry.get("image_url") or "").strip()
        results.append({
            "listing_url": listing_url,
            "product_url": entry["product_url"],
            "image_url": urljoin(BASE_DOMAIN, image) if image and not is_placeholder_image(image) else "",
        })

    # Anything repeated across this page is a stand-in whatever its filename, so
    # drop it and let the detail page supply the real photo.
    counts = Counter(r["image_url"] for r in results if r["image_url"])
    reused = {url for url, n in counts.items() if n >= PLACEHOLDER_REUSE_LIMIT}
    if reused:
        for result in results:
            if result["image_url"] in reused:
                result["image_url"] = ""
        print(f"[INFO] Ignored {len(reused)} image(s) reused across this page")

    print(f"[DEBUG] Found {len(results)} product links")
    return results


def scrape_detail_image(page, product_url: str) -> str:
    """
    Fallback: if listing image is still a loader gif or missing, grab a real product image from the detail page.
    """
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)

        images = page.locator("img")
        count = images.count()

        # Only a real product photo will do. There is deliberately no looser
        # second pass: the previous version fell back to "any image that is not
        # a spinner", which is how every ball without a photo ended up showing
        # the same site logo. No image beats the wrong image.
        for i in range(count):
            candidate = extract_best_image_url(images.nth(i))
            if candidate and is_product_image(candidate):
                return urljoin(BASE_DOMAIN, candidate)

        return ""
    except Exception:
        return ""


# Storm runs two product page templates. The absolute XPaths below only match
# the older one; on the newer pages they hit nothing, so the SKU fell through to
# "the first h4 on the page" - the shopping cart - and the price fell through to
# OUT_OF_STOCK, which hid the product from shoppers entirely. That is why the
# Tropical Surge balls looked missing while the older balls priced correctly.
#
# The newer template declares what it is in its own script block, which is more
# dependable than any selector:
#     var ITEM_ID    = "BBMVTY"
#     var ITEM_IMAGE = ".../contents/BBMVTY/BBMVTY.png"
EXTRACT_DETAIL_JS = r"""
() => {
  const html = document.documentElement.innerHTML;
  const jsVar = (name) => {
    const m = html.match(new RegExp('var\\s+' + name + '\\s*=\\s*"([^"]*)"'));
    return m ? m[1].trim() : '';
  };

  // The price lives with the product, never in the basket summary or the mini
  // cart - every ".money" and ".price" on a logged-out page belongs to those.
  const inCart = (el) => !!el.closest(
    '.preview-cart, .module-basket-summary, .dropdown-toggle, .mini-cart, .cart-totals'
  );
  let price = '';
  const scopes = document.querySelectorAll('.product-shop, .module-product-details, #grid');
  for (const scope of scopes) {
    for (const el of scope.querySelectorAll('span, div, p, strong, b')) {
      if (el.children.length || inCart(el)) continue;
      const text = (el.textContent || '').trim();
      const m = text.match(/^\$\s?([\d,]+\.\d{2})$/);
      if (m && parseFloat(m[1].replace(/,/g, '')) > 0) { price = text; break; }
    }
    if (price) break;
  }

  // "SKU: BBMVTY" sits in the product title block on the new template.
  let sku = jsVar('ITEM_ID');
  if (!sku) {
    for (const el of document.querySelectorAll('h4, .item-code, .product-name *')) {
      const m = (el.textContent || '').match(/SKU:\s*([A-Za-z0-9._-]+)/);
      if (m) { sku = m[1]; break; }
    }
  }

  return {
    sku: sku || '',
    name: jsVar('ITEM_NAME') || jsVar('ITEM_HEADING') ||
          (document.querySelector('h1') || {}).textContent || '',
    image: jsVar('ITEM_IMAGE') || '',
    price: price,
  };
}
"""


# Storm throttles a fast scraper by serving a holding page. It returns HTTP 200
# and the old code stored it as a product: two rows came back named "Busy in
# processing", losing prices they had had the run before. Silent corruption is
# worse than a slow scrape, so these are detected and retried.
THROTTLE_MARKERS = ("busy in processing", "please wait", "too many requests")
THROTTLE_RETRIES = 3
THROTTLE_BACKOFF_MS = 4000


def looks_throttled(page) -> bool:
    try:
        heading = (page.inner_text("body", timeout=4000) or "")[:600].lower()
    except Exception:
        return False
    return any(marker in heading for marker in THROTTLE_MARKERS)


def parse_sku(raw_text: str) -> str:
    raw_text = clean_text(raw_text)
    if not raw_text:
        return ""

    raw_text = re.sub(r"^\s*SKU:\s*", "", raw_text, flags=re.IGNORECASE).strip()
    return raw_text


def extract_scent(page) -> str:
    """
    Return the fragrance/scent value if present, otherwise 'none'.
    """
    # First try the full paragraph text, which is usually more reliable than the <strong> label alone.
    scent_p_text = text_or_empty(page.locator(f"xpath={SCENT_P_XPATH}"))
    if scent_p_text:
        match = re.search(r"Fragrance:\s*(.+)", scent_p_text, flags=re.IGNORECASE)
        if match:
            value = clean_text(match.group(1))
            return value if value else "none"

    # Backup: inspect the strong label and its parent
    strong_locator = page.locator(f"xpath={SCENT_STRONG_XPATH}")
    if strong_locator.count() > 0:
        try:
            parent_text = clean_text(strong_locator.first.locator("xpath=..").text_content(timeout=3000) or "")
            match = re.search(r"Fragrance:\s*(.+)", parent_text, flags=re.IGNORECASE)
            if match:
                value = clean_text(match.group(1))
                return value if value else "none"
        except Exception:
            pass

    return "none"


def scrape_product_detail(page, product_url: str):
    detail = {
        "name": "",
        "sku": "",
        "price": "OUT_OF_STOCK",
        "scent": "none",
        "image": "",
    }

    for attempt in range(THROTTLE_RETRIES):
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1000)
        except PlaywrightTimeoutError:
            print(f"[WARN] Timeout loading product page: {product_url}")
            return detail
        except Exception as exc:
            # One unusable link must not end a 25 minute scrape.
            print(f"[WARN] Could not load {product_url}: {exc}")
            return detail

        if not looks_throttled(page):
            break

        wait = THROTTLE_BACKOFF_MS * (attempt + 1)
        print(f"[WARN] Throttled on {product_url}, waiting {wait}ms "
              f"(attempt {attempt + 1}/{THROTTLE_RETRIES})")
        page.wait_for_timeout(wait)
    else:
        # Returning the holding page's text as a product is how two rows ended
        # up named "Busy in processing" with their prices wiped.
        print(f"[WARN] Still throttled, skipping {product_url}")
        return detail

    # What the page says about itself, which works on both templates.
    try:
        declared = page.evaluate(EXTRACT_DETAIL_JS) or {}
    except Exception:
        declared = {}

    name = clean_text(declared.get("name") or "")
    sku = parse_sku(declared.get("sku") or "")
    detail["image"] = str(declared.get("image") or "").strip()

    # Price takes the long-standing path first. It priced 334 products correctly
    # on the last run, and money is the one field where a plausible wrong answer
    # is worse than none - the text search below is a fallback for the pages it
    # misses, not a replacement.
    price = text_or_empty(page.locator(f"xpath={PRICE_XPATH}"))
    if not price:
        price = clean_text(declared.get("price") or "")

    # Fall back to the old template's absolute paths for the rest.
    if not name:
        name = text_or_empty(page.locator(f"xpath={NAME_XPATH}"))
    if not sku:
        # The full h4, so we get the value rather than just the label span.
        sku = parse_sku(text_or_empty(page.locator(f"xpath={SKU_H4_XPATH}")))

    scent = extract_scent(page)

    if not name:
        name = text_or_empty(page.locator("h1"))

    if not sku:
        # Deliberately not "the first h4 on the page": on the newer template
        # that is the shopping cart, which is how 17 products ended up with a
        # SKU of "Shopping Cart Cart is Empty".
        try:
            sku_label_locator = page.locator(f"xpath={SKU_LABEL_XPATH}")
            if sku_label_locator.count() > 0:
                parent_text = clean_text(sku_label_locator.first.locator("xpath=..").text_content(timeout=3000) or "")
                sku = parse_sku(parent_text)
        except Exception:
            pass

    if not price:
        price = "OUT_OF_STOCK"

    detail["name"] = name
    detail["sku"] = sku
    detail["price"] = price
    detail["scent"] = scent
    return detail


def write_csv(rows, output_csv):
    fieldnames = ["listing_url", "product_url", "image_url", "name", "sku", "price",
                  "scent", "main_category", "sub_category"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if SETUP_LOGIN:
        save_auth_state()
        return 0

    all_rows = []

    with sync_playwright() as p:
        browser, context = open_browser_context(p)

        listing_page = context.new_page()
        detail_page = context.new_page()

        # Walk the category tree, which labels each product as it goes. Falls
        # back to the numbered listing pages if no categories can be read.
        sources = []
        if USE_CATEGORY_WALK:
            for category in discover_category_pages(listing_page):
                sources.append({
                    "url": f"{category['url']}?per_page={CATEGORY_PAGE_SIZE}",
                    "main_category": category["main_category"],
                    "sub_category": category["sub_category"],
                })
        if not sources:
            print("[WARN] No categories found, falling back to the numbered listing pages")
            sources = [
                {"url": LISTING_URL_TEMPLATE.format(page=n), "main_category": "", "sub_category": ""}
                for n in range(START_PAGE, END_PAGE + 1)
            ]

        seen_products: set[str] = set()

        for position, source in enumerate(sources, start=1):
            listing_url = source["url"]
            label = source["sub_category"] or f"page {position}"
            print(f"[INFO] [{position}/{len(sources)}] {label}: {listing_url}")

            listing_items = collect_listing_items(listing_page, listing_url)

            # Check the session on the first page whatever came back. Checking
            # only when the list was empty missed the case that actually
            # happened: a logged-out scrape still returns links, it just prices
            # them at retail instead of the team's sponsor rate - and then spent
            # 42 minutes collecting the wrong numbers.
            if position == 1:
                if looks_logged_out(listing_page):
                    browser.close()
                    print(
                        "\n[ERROR] Not signed in to stormbowling.com.\n"
                        "        Prices on this site are the public retail ones unless the\n"
                        "        scraper is signed in, so continuing would collect the wrong\n"
                        f"        figures. The saved session in {AUTH_STATE_FILE} is not working.\n\n"
                        "        Regenerate it locally with:\n"
                        "            SCRAPER_SETUP_LOGIN=true python storm_scraper.py\n"
                        "        then update the STORM_AUTH_STATE secret.\n\n"
                        "        If a freshly saved session still fails here but works on your\n"
                        "        own machine, Storm is probably tying the login to the browser\n"
                        "        or network it was created on, and the scrape has to be run\n"
                        "        locally rather than from CI."
                    )
                    return 2
                if not listing_items:
                    print("[WARN] First listing page returned no products while apparently "
                          "signed in - the page layout may have changed.")

            # A product can sit in more than one category listing; the first one
            # wins so it is only fetched and priced once.
            listing_items = [i for i in listing_items if i["product_url"] not in seen_products]
            seen_products.update(i["product_url"] for i in listing_items)

            print(f"[INFO] {len(listing_items)} new product(s) in {label}")

            for idx, item in enumerate(listing_items, start=1):
                print(f"   [{idx}/{len(listing_items)}] {item['product_url']}")

                detail = scrape_product_detail(detail_page, item["product_url"])

                image_url = item["image_url"]
                if not is_product_image(image_url):
                    # The page's own ITEM_IMAGE is authoritative - it is the
                    # product's picture by definition, so it does not have to
                    # match the thumbnail path the listing images use.
                    declared = detail.get("image", "")
                    if declared and not is_loader_image(declared):
                        image_url = urljoin(BASE_DOMAIN, declared)
                    else:
                        fallback_image = scrape_detail_image(detail_page, item["product_url"])
                        image_url = fallback_image if is_product_image(fallback_image) else ""

                row = {
                    "listing_url": item["listing_url"],
                    "product_url": item["product_url"],
                    "image_url": image_url,
                    "name": detail["name"],
                    "sku": detail["sku"],
                    "price": detail["price"],
                    "scent": detail["scent"],
                    # From the category page this came off, so it is known
                    # rather than inferred from the product slug afterwards.
                    "main_category": source["main_category"],
                    "sub_category": source["sub_category"],
                }
                all_rows.append(row)

                time.sleep(0.25)

        browser.close()

    if not all_rows:
        # Writing an empty CSV here used to push the failure downstream, where
        # label_cleaning.py died with "Columns must be same length as key".
        print("\n[ERROR] Scraped 0 products. Nothing was written; the previous "
              f"{OUTPUT_CSV} is left untouched.")
        return 2

    # Last net, across the whole run rather than one page: a photo belongs to a
    # single product, so anything shared is a stand-in that slipped through.
    counts = Counter(r["image_url"] for r in all_rows if r["image_url"])
    shared = {url for url, n in counts.items() if n >= PLACEHOLDER_REUSE_LIMIT}
    if shared:
        for row in all_rows:
            if row["image_url"] in shared:
                row["image_url"] = ""
        print(f"[INFO] Dropped {len(shared)} image(s) shared between products")

    with_image = sum(1 for r in all_rows if r["image_url"])
    ratio = with_image / len(all_rows)
    print(f"[INFO] {with_image} of {len(all_rows)} products have a photo "
          f"({ratio:.0%}); the rest have none on the site")

    if ratio < MIN_EXPECTED_IMAGE_RATIO:
        print(f"[WARN] That is below the {MIN_EXPECTED_IMAGE_RATIO:.0%} expected. "
              f"If Storm moved their images off the '{PRODUCT_IMAGE_MARKER}' path, "
              "PRODUCT_IMAGE_MARKER needs updating - the catalog will show "
              "missing images until it is.")

    write_csv(all_rows, OUTPUT_CSV)
    print(f"\nDone. Wrote {len(all_rows)} rows to {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())