import pandas as pd
from urllib.parse import urlparse

INPUT_CSV = "storm_products.csv"
OUTPUT_CSV = "storm_products_tagged.csv"

MAIN_CATEGORY_MAP = {
    "equipment": "Equipment",
    "bowling-essentials": "Bowling Essentials",
    "merchandise": "Merchandise",
    "collections": "Collections",
}

SUBCATEGORY_MAP = {
    "bowling-balls": "Bowling Balls",
    "bowling-bags": "Bowling Bags",
    "shoes": "Shoes",
    "shoe-accessories": "Shoe Accessories",
    "grip-aids": "Grip Aids",
    "supports-gloves": "Supports & Gloves",
    "tape": "Tape",
    "towels": "Towels",
    "pro-shop-supplies": "Pro Shop Supplies",
    "cleaners-polishes": "Cleaners & Polishes",
    "apparel": "Apparel",
    "accessories": "Accessories",
    "gifts-and-collectibles": "Gifts and Collectibles",
    "collections": "Collections",
}


def parse_categories(url):
    try:
        path = urlparse(str(url)).path.strip("/")
        parts = path.split("/")

        if len(parts) >= 4 and parts[0] == "products":
            main_raw = parts[1]
            sub_raw = parts[2]

            main_category = MAIN_CATEGORY_MAP.get(
                main_raw, main_raw.replace("-", " ").title()
            )
            sub_category = SUBCATEGORY_MAP.get(
                sub_raw, sub_raw.replace("-", " ").title()
            )

            return pd.Series([main_category, sub_category])

        return pd.Series(["Unknown", "Unknown"])
    except Exception:
        return pd.Series(["Unknown", "Unknown"])


df = pd.read_csv(INPUT_CSV)

# An empty scrape used to reach this point and fail inside pandas with
# "Columns must be same length as key", which says nothing about the real cause.
if df.empty:
    raise SystemExit(
        f"{INPUT_CSV} has no rows, so there is nothing to tag.\n"
        "The scrape came back empty - usually an expired stormbowling.com "
        "session. Regenerate it with:\n"
        "    SCRAPER_SETUP_LOGIN=true python storm_scraper.py"
    )

if "product_url" not in df.columns:
    raise SystemExit(f"{INPUT_CSV} has no product_url column: {sorted(df.columns)}")

# The scraper now walks the category tree, so it already knows which category
# each product was listed under. Only fill in what it could not supply.
#
# Deriving from the URL is the fallback, and it must not forward-fill. It used
# to, which was harmless when every product sat under /products/<main>/<sub>/;
# once Storm moved products to root-level URLs the fill labelled bowling balls
# "Apparel" or "Shoe Accessories" purely from whatever was scraped before them.
# Unknown is recoverable - catalog.py re-reads the category from the slug - but a
# confident wrong answer is not.
derived = df["product_url"].apply(parse_categories)
derived.columns = ["main_derived", "sub_derived"]
df = pd.concat([df, derived], axis=1)

for column, fallback in (("main_category", "main_derived"), ("sub_category", "sub_derived")):
    if column not in df.columns:
        df[column] = pd.NA
    known = df[column].astype("string").str.strip()
    known = known.mask(known.isin(["", "Unknown", "nan", "None"]))
    df[column] = known.fillna(df[fallback]).fillna("Unknown")

df = df.drop(columns=["main_derived", "sub_derived"])

from_scraper = (df["sub_category"] != "Unknown").sum()
print(f"{from_scraper} of {len(df)} products have a category; "
      f"{len(df) - from_scraper} unknown")

df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved cleaned file to {OUTPUT_CSV}")
print(df[["product_url", "main_category", "sub_category"]].head(15))