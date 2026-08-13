"""
Recompress the scraped catalog images.

The images saved by download_images.py come off stormbowling.com as 600x600 RGBA
PNGs with no compression applied - 1.4 MB each, ~343 MB for the full catalog.
That is far more than the app needs (cards render the image around 300 px wide)
and it is the single biggest cause of slow page loads.

This converts everything to WebP at a sensible display size, which takes the set
down to roughly 7 MB with no visible quality loss.

Usage:
    python optimize_images.py                      # convert, keep originals
    python optimize_images.py --delete-originals   # convert, then remove the PNGs

Requires Pillow (not needed at runtime, only for this script):
    pip install Pillow
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

IMAGE_DIR = Path('static/catalog_images')
CATALOG_CSV = Path('storm_products_tagged.csv')
SOURCE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif'}


def human(num_bytes: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(num_bytes) < 1024:
            return f'{num_bytes:,.1f} {unit}'
        num_bytes /= 1024
    return f'{num_bytes:,.1f} TB'


def convert_one(source: Path, max_size: int, quality: int) -> Path | None:
    """Write a WebP alongside `source` and return its path, or None on failure."""
    target = source.with_suffix('.webp')
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target

    try:
        with Image.open(source) as img:
            img.load()
            # Palette images with transparency need RGBA to survive the resize.
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA' if 'transparency' in img.info else 'RGB')

            img.thumbnail((max_size, max_size), Image.LANCZOS)
            img.save(target, 'WEBP', quality=quality, method=6)
        return target
    except Exception as exc:
        print(f'  FAILED {source.name}: {exc}')
        return None


def update_catalog_csv(mapping: dict[str, str]) -> int:
    """Repoint the CSV's image_url column at the converted files."""
    if not CATALOG_CSV.exists():
        print(f'\nSkipping CSV update, {CATALOG_CSV} not found.')
        return 0

    df = pd.read_csv(CATALOG_CSV)
    if 'image_url' not in df.columns:
        print(f'\nSkipping CSV update, no image_url column in {CATALOG_CSV}.')
        return 0

    # A product can have no image: download_images.py leaves the cell empty when
    # a fetch fails, which it did for 3 of 427 products on one run. pandas hands
    # that back as NaN, and with its pyarrow backend .astype(str) leaves it as
    # NA rather than the string "nan" - so calling .strip() on it raised
    # AttributeError and killed the step after 423 images had already been
    # converted, taking the whole refresh with it.
    original = df['image_url']

    def repoint(value):
        if not isinstance(value, str):
            return value
        return mapping.get(value.strip(), value)

    updated = original.map(repoint)

    def comparable(series):
        return series.astype('string').fillna('')

    changed = int((comparable(updated) != comparable(original)).sum())
    df['image_url'] = updated

    if changed:
        df.to_csv(CATALOG_CSV, index=False)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=450,
                        help='longest edge in pixels (default: 450)')
    parser.add_argument('--quality', type=int, default=80,
                        help='WebP quality 1-100 (default: 80)')
    parser.add_argument('--delete-originals', action='store_true',
                        help='remove the source files after a successful convert')
    args = parser.parse_args()

    if not IMAGE_DIR.is_dir():
        print(f'No image directory at {IMAGE_DIR.resolve()}')
        return 1

    sources = sorted(
        p for p in IMAGE_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES
    )

    if not sources:
        print(f'Nothing to convert in {IMAGE_DIR} - already optimized?')
        return 0

    print(f'Converting {len(sources)} images at {args.size}px / quality {args.quality}...')

    bytes_before = 0
    bytes_after = 0
    mapping: dict[str, str] = {}
    converted: list[tuple[Path, Path]] = []

    for source in sources:
        target = convert_one(source, args.size, args.quality)
        if target is None:
            continue

        bytes_before += source.stat().st_size
        bytes_after += target.stat().st_size
        mapping[source.as_posix()] = target.as_posix()
        converted.append((source, target))

    if not converted:
        print('No images were converted.')
        return 1

    print(f'\nConverted {len(converted)} images')
    print(f'  before: {human(bytes_before)}')
    print(f'  after:  {human(bytes_after)}')
    if bytes_after:
        print(f'  saved:  {human(bytes_before - bytes_after)} '
              f'({bytes_before / bytes_after:.0f}x smaller)')

    changed = update_catalog_csv(mapping)
    print(f'\nRepointed {changed} rows in {CATALOG_CSV}')

    if args.delete_originals:
        for source, _ in converted:
            source.unlink()
        print(f'Deleted {len(converted)} original files')
    else:
        print('\nOriginals kept. Re-run with --delete-originals once you are happy '
              'with how the images look.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
