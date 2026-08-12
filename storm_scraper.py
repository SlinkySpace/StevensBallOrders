import csv
import os
import re
import sys
import time
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
  const NON_PRODUCT_ROOTS = new Set([
    'products','company','events','community','cart','account','login','register',
    'logout','search','contact','about','news','blog','dealers','sitemap',
    'privacy-policy','terms-of-use','terms-and-conditions','terms-of-service',
    'shipping-policy','return-policy','my-account','order-history','contact-us',
    'about-us','where-to-buy','find-a-dealer','customer-service'
  ]);

  const bareHost = (h) => (h || '').replace(/^www\\./, '').toLowerCase();

  const isProduct = (href) => {
    if (!href) return false;

    let url;
    try { url = new URL(href, location.origin); } catch (e) { return false; }

    // Without these two checks "tel:(435)-723-0403" parses to a pathname of
    // "(435)-723-0403", which the root-slug rule below happily accepted - and
    // the scraper then tried to navigate to it.
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
    if (bareHost(url.hostname) !== bareHost(location.hostname)) return false;

    const parts = url.pathname.split('/').filter(Boolean);
    if (!parts.length) return false;

    if (parts[0] === 'products') {
      return parts.length >= 4 && !/^\\d+$/.test(parts[1]);
    }
    // Root-level product page, e.g. /900-global-2-ball-deluxe-tote
    const slug = parts[0].toLowerCase();
    return parts.length === 1
        && /^[a-z0-9][a-z0-9-]*$/.test(slug)
        && slug.includes('-')
        && !NON_PRODUCT_ROOTS.has(slug);
  };

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

  const seen = new Set();
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href');
    if (!isProduct(href)) continue;
    const abs = new URL(href, location.origin).href;
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
    scroll_listing_page(page)
    page.wait_for_timeout(1200)

    try:
        found = page.evaluate(EXTRACT_LISTING_ITEMS_JS)
    except Exception as exc:
        print(f"[WARN] Could not read products from {listing_url}: {exc}")
        return []

    if not found:
        print(f"[INFO] No products found on {listing_url}")
        return []

    results = []
    for entry in found:
        image = str(entry.get("image_url") or "").strip()
        results.append({
            "listing_url": listing_url,
            "product_url": entry["product_url"],
            "image_url": urljoin(BASE_DOMAIN, image) if image and not is_loader_image(image) else "",
        })

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

        # Prefer product-like images first
        for i in range(count):
            img_locator = images.nth(i)
            candidate = extract_best_image_url(img_locator)
            if candidate and not is_loader_image(candidate):
                lowered = candidate.lower()
                if (
                    "contents/" in lowered
                    or "thumbnail/" in lowered
                    or "product" in lowered
                    or "uploads" in lowered
                ):
                    return urljoin(BASE_DOMAIN, candidate)

        # Fall back to any non-loader image
        for i in range(count):
            img_locator = images.nth(i)
            candidate = extract_best_image_url(img_locator)
            if candidate and not is_loader_image(candidate):
                return urljoin(BASE_DOMAIN, candidate)

        return ""
    except Exception:
        return ""


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
        "scent": "none"
    }

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

    name = text_or_empty(page.locator(f"xpath={NAME_XPATH}"))

    # Pull SKU from the full h4 so we get the value, not just the label span
    sku_raw = text_or_empty(page.locator(f"xpath={SKU_H4_XPATH}"))
    sku = parse_sku(sku_raw)

    price = text_or_empty(page.locator(f"xpath={PRICE_XPATH}"))
    scent = extract_scent(page)

    if not price:
        price = "OUT_OF_STOCK"

    if not name:
        name = text_or_empty(page.locator("h1"))

    if not sku:
        # Backup 1: get generic h4 text and strip SKU:
        sku = parse_sku(text_or_empty(page.locator("h4")))

    if not sku:
        # Backup 2: get the label span's parent h4 text if possible
        try:
            sku_label_locator = page.locator(f"xpath={SKU_LABEL_XPATH}")
            if sku_label_locator.count() > 0:
                parent_text = clean_text(sku_label_locator.first.locator("xpath=..").text_content(timeout=3000) or "")
                sku = parse_sku(parent_text)
        except Exception:
            pass

    detail["name"] = name
    detail["sku"] = sku
    detail["price"] = price
    detail["scent"] = scent
    return detail


def write_csv(rows, output_csv):
    fieldnames = ["listing_url", "product_url", "image_url", "name", "sku", "price", "scent"]
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

        for page_num in range(START_PAGE, END_PAGE + 1):
            listing_url = LISTING_URL_TEMPLATE.format(page=page_num)
            print(f"[INFO] Listing page {page_num}: {listing_url}")

            listing_items = collect_listing_items(listing_page, listing_url)

            # Storm shows the dealer catalog only to a signed-in account. Bail on
            # the first page rather than grinding through 19 empty ones.
            if page_num == START_PAGE and not listing_items:
                if looks_logged_out(listing_page):
                    browser.close()
                    print(
                        "\n[ERROR] Not signed in to stormbowling.com. The saved session "
                        f"in {AUTH_STATE_FILE} has expired.\n"
                        "        Regenerate it with SCRAPER_SETUP_LOGIN=true python storm_scraper.py\n"
                        "        and update the STORM_AUTH_STATE secret.",
                    )
                    return 2
                print("[WARN] First listing page returned no products while apparently "
                      "signed in - the page layout may have changed.")

            print(f"[INFO] Found {len(listing_items)} products on page {page_num}")

            for idx, item in enumerate(listing_items, start=1):
                print(f"   [{idx}/{len(listing_items)}] {item['product_url']}")

                detail = scrape_product_detail(detail_page, item["product_url"])

                image_url = item["image_url"]
                if (not image_url) or is_loader_image(image_url):
                    fallback_image = scrape_detail_image(detail_page, item["product_url"])
                    if fallback_image and not is_loader_image(fallback_image):
                        image_url = fallback_image

                row = {
                    "listing_url": item["listing_url"],
                    "product_url": item["product_url"],
                    "image_url": image_url,
                    "name": detail["name"],
                    "sku": detail["sku"],
                    "price": detail["price"],
                    "scent": detail["scent"]
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

    write_csv(all_rows, OUTPUT_CSV)
    print(f"\nDone. Wrote {len(all_rows)} rows to {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())