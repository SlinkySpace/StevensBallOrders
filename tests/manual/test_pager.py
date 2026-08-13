"""
Exercise the real pager walk from storm_scraper, without the per-product detail
fetch. Counts what a full scrape would now find.
"""
import os, sys
from collections import Counter

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(APP); sys.path.insert(0, APP)
os.environ.setdefault("SCRAPER_HEADLESS", "true")

from playwright.sync_api import sync_playwright
import storm_scraper as S

with sync_playwright() as p:
    browser, context = S.open_browser_context(p)
    page = context.new_page()

    cats = S.discover_category_pages(page)
    print(f"\nlogged out? {S.looks_logged_out(page)}\n")

    sources = [{"url": c["url"], "sub_category": c["sub_category"], "group": c["url"], "page_no": 1}
               for c in cats]
    queued = {s["url"] for s in sources}
    pages_per_group = Counter(s["group"] for s in sources)

    seen: set[str] = set()
    per_cat: dict[str, int] = {}
    i = 0
    while i < len(sources):
        src = sources[i]; i += 1
        items = S.collect_listing_items(page, src["url"])
        fresh = [x for x in items if x["product_url"] not in seen]
        seen.update(x["product_url"] for x in fresh)
        per_cat[src["sub_category"]] = per_cat.get(src["sub_category"], 0) + len(fresh)

        label = src["sub_category"] + (f" p{src['page_no']}" if src["page_no"] > 1 else "")
        print(f"  {label:<30} {len(items):>3} on page, {len(fresh):>3} new")

        for url in S.read_pager_urls(page, src["group"]):
            if url in queued or pages_per_group[src["group"]] >= S.CATEGORY_MAX_PAGES:
                continue
            queued.add(url); pages_per_group[src["group"]] += 1
            sources.append({"url": url, "sub_category": src["sub_category"],
                            "group": src["group"], "page_no": pages_per_group[src["group"]]})

    browser.close()

print("\n--- per category ---")
for name, n in sorted(per_cat.items()):
    pages = pages_per_group[f"https://www.stormbowling.com/products/"
                            f"{'':s}"] if False else None
    print(f"  {name:<30} {n:>3}")

print(f"\n  listing pages visited : {len(sources)}")
print(f"  unique products found : {len(seen)}")
print(f"  previous broken scrape: 268")
print(f"  guard minimum         : 300")
print("\n  " + ("CLEARS the guard" if len(seen) >= 300 else "STILL BELOW the guard"))
