from pathlib import Path
from urllib.parse import urlparse
import hashlib
import mimetypes

import pandas as pd
import requests

CATALOG_CSV = Path("storm_products_tagged.csv")
OUTPUT_DIR = Path("static/catalog_images")
REQUEST_TIMEOUT = 20

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(CATALOG_CSV)
if "image_url" not in df.columns:
    raise ValueError("CSV is missing the image_url column.")

session = requests.Session()
downloaded = 0
skipped = 0
failed = 0

for idx, row in df.iterrows():
    url = str(row.get("image_url", "") or "").strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        skipped += 1
        continue

    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        guessed, _ = mimetypes.guess_type(parsed.path)
        if guessed == "image/png":
            suffix = ".png"
        elif guessed == "image/webp":
            suffix = ".webp"
        elif guessed == "image/gif":
            suffix = ".gif"
        else:
            suffix = ".jpg"

    sku = str(row.get("sku", "") or "").strip()
    slug_source = sku if sku else str(row.get("name", f"item_{idx}"))
    safe_slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in slug_source).strip("_")
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    filename = f"{safe_slug}_{url_hash}{suffix}"
    output_path = OUTPUT_DIR / filename

    if output_path.exists():
        df.at[idx, "image_url"] = str(output_path.as_posix())
        skipped += 1
        continue

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "image" not in content_type:
            failed += 1
            continue

        output_path.write_bytes(response.content)
        df.at[idx, "image_url"] = str(output_path.as_posix())
        downloaded += 1
    except Exception as exc:
        print(f"FAILED: {url} -> {exc}")
        failed += 1

df.to_csv(CATALOG_CSV, index=False)

print(f"Downloaded: {downloaded}")
print(f"Skipped: {skipped}")
print(f"Failed: {failed}")
print(f"Updated CSV: {CATALOG_CSV.resolve()}")
