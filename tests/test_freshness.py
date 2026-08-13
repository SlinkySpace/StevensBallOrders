import os, sys
from datetime import datetime, timedelta
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(APP); sys.path.insert(0, APP)

from catalog_admin import _humanize_age, STALE_CATALOG_DAYS

now = datetime.now()
cases = [
    (now, 'just now', 0),
    (now - timedelta(minutes=30), 'just now', 0),
    (now - timedelta(hours=1, minutes=5), '1 hour ago', 0),
    (now - timedelta(hours=5), '5 hours ago', 0),
    (now - timedelta(days=1, hours=1), 'yesterday', 1),
    (now - timedelta(days=6), '6 days ago', 6),
    (now - timedelta(days=29), '29 days ago', 29),
    (now - timedelta(days=45), 'about 1 month ago', 45),
    (now - timedelta(days=200), 'about 6 months ago', 200),
]

ok = True
for moment, expected_label, expected_days in cases:
    label, days = _humanize_age(moment.isoformat(timespec='seconds'))
    good = label == expected_label and days == expected_days
    ok &= good
    flag = 'stale' if days >= STALE_CATALOG_DAYS else 'fresh'
    print(f"{'PASS' if good else 'FAIL'}  {label:<22} days={days:<5} -> {flag}"
          + ('' if good else f"   expected {expected_label!r}/{expected_days}"))

for bad in (None, '', 'not-a-date', 12345):
    label, days = _humanize_age(bad)
    good = label == 'unknown' and days > STALE_CATALOG_DAYS
    ok &= good
    print(f"{'PASS' if good else 'FAIL'}  malformed {bad!r} -> {label!r} (treated as stale)")

print(f"\nSTALE_CATALOG_DAYS = {STALE_CATALOG_DAYS}")
print('ALL PASS' if ok else 'FAILURES')
sys.exit(0 if ok else 1)
