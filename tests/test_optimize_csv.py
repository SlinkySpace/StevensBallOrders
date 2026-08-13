"""update_catalog_csv must survive products whose image download failed."""
import os, sys, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import pandas as pd
import optimize_images

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

tmp = Path(tempfile.gettempdir()) / "opt_csv_test.csv"
MAPPING = {
    'static/catalog_images/ball.png': 'static/catalog_images/ball_ab12.webp',
    'static/catalog_images/shoe.jpg': 'static/catalog_images/shoe_cd34.webp',
}

BASE = pd.DataFrame({
    'product_url': ['a', 'b', 'c', 'd'],
    'name': ['BALL', 'SHOE', 'NO IMAGE', 'UNCONVERTED'],
    # row c is the failed download: empty cell -> NaN on read
    'image_url': ['static/catalog_images/ball.png',
                  'static/catalog_images/shoe.jpg',
                  '',
                  'static/catalog_images/other.png'],
})

for backend in ('numpy', 'pyarrow'):
    print(f"\n== dtype_backend={backend} ==")
    BASE.to_csv(tmp, index=False)
    optimize_images.CATALOG_CSV = tmp

    real_read = pd.read_csv
    def read_with_backend(*a, **k):
        if backend == 'pyarrow':
            k.setdefault('dtype_backend', 'pyarrow')
        return real_read(*a, **k)
    pd.read_csv = read_with_backend
    try:
        changed = optimize_images.update_catalog_csv(MAPPING)
        crashed = None
    except Exception as exc:
        changed, crashed = None, exc
    finally:
        pd.read_csv = real_read

    check(f"[{backend}] does not crash on a missing image_url", crashed is None, repr(crashed))
    if crashed:
        continue

    out = pd.read_csv(tmp)
    got = {r['name']: ('' if pd.isna(r['image_url']) else r['image_url'])
           for _, r in out.iterrows()}
    check(f"[{backend}] converted image repointed",
          got['BALL'] == 'static/catalog_images/ball_ab12.webp', str(got['BALL']))
    check(f"[{backend}] second image repointed",
          got['SHOE'] == 'static/catalog_images/shoe_cd34.webp', str(got['SHOE']))
    check(f"[{backend}] failed download stays empty, not 'nan'",
          got['NO IMAGE'] == '', repr(got['NO IMAGE']))
    check(f"[{backend}] an unmapped image is left alone",
          got['UNCONVERTED'] == 'static/catalog_images/other.png', str(got['UNCONVERTED']))
    check(f"[{backend}] reports 2 changed rows", changed == 2, str(changed))

print("\n== nothing to change ==")
BASE.to_csv(tmp, index=False)
optimize_images.CATALOG_CSV = tmp
check("an empty mapping changes nothing", optimize_images.update_catalog_csv({}) == 0)

tmp.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
