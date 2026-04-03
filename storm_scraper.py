import csv
import os
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DOMAIN = "https://www.stormbowling.com"
START_PAGE = 1
END_PAGE = 19
OUTPUT_CSV = "storm_products.csv"
AUTH_STATE_FILE = "storm_auth_state.json"

# First run:
#   SETUP_LOGIN = True
#   HEADLESS_SCRAPE = False
#
# After auth state is saved:
#   SETUP_LOGIN = False
#   HEADLESS_SCRAPE = True
SETUP_LOGIN = False
HEADLESS_SCRAPE = True

# True = use installed Microsoft Edge channel
# False = use bundled Chromium
USE_EDGE_CHANNEL = True

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
    results = []

    page.goto(listing_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1800)

    scroll_listing_page(page)
    page.wait_for_timeout(1200)

    list_container = page.locator(f"xpath={LIST_CONTAINER_XPATH}")
    if list_container.count() == 0:
        print(f"[WARN] Could not find product list on {listing_url}")
        return results

    items = list_container.locator("xpath=./li")
    item_count = items.count()
    print(f"[DEBUG] Found {item_count} li elements")

    if item_count == 0:
        print(f"[INFO] No products found on {listing_url}")
        return results

    for i in range(item_count):
        item = items.nth(i)

        link_locator = item.locator("xpath=./div/div[3]/div/a")
        img_locator = item.locator("xpath=./div/div[3]/div/a/img")

        href = attr_or_empty(link_locator, "href")
        if not href:
            continue

        # Retry image extraction a few times to let lazy-loading settle
        img_src = ""
        for _ in range(4):
            candidate = extract_best_image_url(img_locator)
            if candidate and not is_loader_image(candidate):
                img_src = candidate
                break
            page.wait_for_timeout(350)

        product_url = urljoin(BASE_DOMAIN, href)
        image_url = urljoin(BASE_DOMAIN, img_src) if img_src else ""

        results.append({
            "listing_url": listing_url,
            "product_url": product_url,
            "image_url": image_url
        })

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
        return

    all_rows = []

    with sync_playwright() as p:
        browser, context = open_browser_context(p)

        listing_page = context.new_page()
        detail_page = context.new_page()

        for page_num in range(START_PAGE, END_PAGE + 1):
            listing_url = LISTING_URL_TEMPLATE.format(page=page_num)
            print(f"[INFO] Listing page {page_num}: {listing_url}")

            listing_items = collect_listing_items(listing_page, listing_url)
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

    write_csv(all_rows, OUTPUT_CSV)
    print(f"\nDone. Wrote {len(all_rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()