# Tests

```bash
python tests/run_all.py
```

No test framework and no dependencies beyond what the app already needs. Each
test is a plain script that prints its own PASS/FAIL lines and exits non-zero if
anything failed; `run_all.py` runs them and shows the full output of whichever
ones fail.

Every test builds its own state in a throwaway SQLite file under the system temp
directory, with `config.DATABASE_URL` blanked first. **None of them touch the
hosted database**, and none reach the network.

## What is covered

| Test | Guards against |
| --- | --- |
| `test_auth` | password hashing, login, the migration for accounts that predate passwords |
| `test_cache_and_pg` | catalog cache invalidation, and the generated Postgres SQL |
| `test_catalog` | CSV to database import, the three merge modes |
| `test_diff` | the Catalog Manager's edit diffing |
| `test_freshness` | the "catalog is getting old" warning |
| `test_optimize_csv` | image repointing when a download failed and the cell is NaN |
| `test_orders` | orders owning multiple items, totals, status changes |
| `test_rekey` | matching a scraped product to a stored one after Storm moves its URL |
| `test_replace` | replace mirrors the file, hand-added products survive |
| `test_replace_safety` | replace preserves price/category/type/hidden, and the delete bound |
| `test_retire` | products Storm stops listing are retired, not deleted |
| `test_scraper_urls` | the product-URL filter that replaced the absolute XPath |
| `test_sync_guards` | the guards that refuse a logged-out or truncated scrape |

The sync guards are the ones worth keeping green: they have already blocked
three bad runs that would otherwise have written retail prices, a duplicated
catalog, and a truncated scrape into the live database.

## `tests/manual/`

Not run by `run_all.py`, because each needs something it cannot assume:

- `test_dedupe.py OLD.csv NEW.csv` — duplicate and junk-row detection across two
  scraper CSVs.
- `test_reimport_stable.py OLD.csv NEW.csv` — checks that re-importing does not
  churn rows.
- `test_pager.py` — drives a real browser against stormbowling.com and counts
  what a full scrape would find, without the per-product detail fetches. Needs
  `playwright install chromium`. Useful for checking the category walk in about
  a minute rather than waiting out a 40-minute scrape.
