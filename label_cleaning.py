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

df[["main_category", "sub_category"]] = df["product_url"].apply(parse_categories)

# Replace Unknown with previous row's category/subcategory
df["main_category"] = df["main_category"].replace("Unknown", pd.NA).ffill().fillna("Unknown")
df["sub_category"] = df["sub_category"].replace("Unknown", pd.NA).ffill().fillna("Unknown")

df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved cleaned file to {OUTPUT_CSV}")
print(df[["product_url", "main_category", "sub_category"]].head(15))