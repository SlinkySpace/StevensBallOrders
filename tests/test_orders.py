"""Order restructure: migration from the legacy one-row-per-item table, plus
the new order/order_items behaviour."""
import os, sys, sqlite3, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "orders_test.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB; config.DATABASE_URL = ""

# --- Build a LEGACY database: one row per item, the old shape ---------------
legacy = sqlite3.connect(DB)
legacy.executescript("""
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT, last_name TEXT,
  email TEXT UNIQUE, saved_card TEXT DEFAULT '', balance_owed REAL DEFAULT 0,
  created_at TEXT);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
  customer_first_name TEXT, customer_last_name TEXT, customer_email TEXT,
  product_name TEXT, sku TEXT, option_type TEXT, option_value TEXT,
  quantity INTEGER, unit_price REAL, total_price REAL, image_url TEXT,
  product_url TEXT, note TEXT, status TEXT, timestamp TEXT,
  main_category TEXT, sub_category TEXT, product_type TEXT);
INSERT INTO users(first_name,last_name,email,balance_owed,created_at)
  VALUES ('Jordan','Ela','jela@stevens.edu',350.0,'2026-03-01T00:00:00');
INSERT INTO users(first_name,last_name,email,balance_owed,created_at)
  VALUES ('CJ','Folgore','cfolgore@stevens.edu',120.0,'2026-03-01T00:00:00');
""")
# Jordan checked out 3 items at once (same timestamp) - one basket.
for name, sku, opt, qty, price in [
    ('EQUINOX','BBMVEQ','15 lb',1,120.0),
    ('ION PRO','BBMVIP','15 lb',1,180.0),
    ('REACTA CLEAN','REACTA_CLEAN','',2,25.0),
]:
    legacy.execute("""INSERT INTO orders(user_id,customer_first_name,customer_last_name,
        customer_email,product_name,sku,option_type,option_value,quantity,unit_price,
        total_price,image_url,product_url,note,status,timestamp,main_category,
        sub_category,product_type) VALUES (1,'Jordan','Ela','jela@stevens.edu',
        ?,?,'Weight',?,?,?,?,'','','','submitted','2026-03-30T22:56:52','Equipment',
        'Bowling Balls',?)""",
        (name, sku, opt, qty, price, qty*price,
         'bowling_ball' if 'BBM' in sku else 'general'))
# Jordan placed a second, separate order later.
legacy.execute("""INSERT INTO orders(user_id,customer_first_name,customer_last_name,
    customer_email,product_name,sku,option_type,option_value,quantity,unit_price,
    total_price,image_url,product_url,note,status,timestamp,main_category,
    sub_category,product_type) VALUES (1,'Jordan','Ela','jela@stevens.edu',
    'TOWEL','TW1','','',1,15.0,15.0,'','','','fulfilled','2026-04-01T10:00:00',
    'Equipment','Towels','general')""")
# CJ has a single-item order.
legacy.execute("""INSERT INTO orders(user_id,customer_first_name,customer_last_name,
    customer_email,product_name,sku,option_type,option_value,quantity,unit_price,
    total_price,image_url,product_url,note,status,timestamp,main_category,
    sub_category,product_type) VALUES (2,'CJ','Folgore','cfolgore@stevens.edu',
    'HUSTLE GLOW','BBMRWQ','Weight','14 lb',1,120.0,120.0,'','','','approved',
    '2026-03-31T09:00:00','Equipment','Bowling Balls','bowling_ball')""")
legacy.commit(); legacy.close()

import db
db.DB_PATH = DB; db.USE_POSTGRES = False

results = []
def check(label, cond, extra=''):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {extra}" if extra and not cond else ''))

print("== migration ==")
db.init_db()

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
tables = {r['name'] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("order_items table created", 'order_items' in tables, str(tables))
check("legacy table preserved as backup", 'orders_legacy_backup' in tables, str(tables))
check("backup still holds all 5 legacy rows",
      con.execute("SELECT COUNT(*) FROM orders_legacy_backup").fetchone()[0] == 5)
check("5 item rows became 3 orders",
      con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3,
      str(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]))
check("all 5 items carried over",
      con.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 5)
check("orders table no longer has item columns",
      'product_name' not in {r['name'] for r in con.execute("PRAGMA table_info(orders)")})
con.close()

print("\n== the 3-item basket regrouped correctly ==")
orders = db.get_orders_for_user(1)
check("Jordan has 2 orders", len(orders) == 2, str(len(orders)))
basket = [o for o in orders if len(o['items']) == 3]
check("one order holds 3 items", len(basket) == 1)
if basket:
    b = basket[0]
    check("basket total is the sum of its lines", abs(float(b['total_price']) - 350.0) < 0.01,
          f"total={b['total_price']} expected 350.0")
    check("basket item_count counts units, not lines", b['item_count'] == 4,
          f"item_count={b['item_count']} expected 4 (1+1+2)")
    check("status preserved", b['status'] == 'submitted', b['status'])
    names = sorted(i['product_name'] for i in b['items'])
    check("all three products present", names == ['EQUINOX','ION PRO','REACTA CLEAN'], str(names))

print("\n== separate checkouts stayed separate ==")
solo = [o for o in orders if len(o['items']) == 1]
check("second order kept its own status", solo and solo[0]['status'] == 'fulfilled',
      str([o['status'] for o in solo]))

print("\n== ball counting through the join ==")
# submitted+approved: 2 balls from Jordan's basket + 1 from CJ = 3
check("pending ball count joins items to orders",
      db.get_pending_ball_orders_count() == 3, str(db.get_pending_ball_orders_count()))
grouped = db.get_grouped_pending_ball_orders()
check("grouped summary returns rows", len(grouped) == 3, str(len(grouped)))
if grouped:
    g = dict(grouped[0])
    check("grouped rows name their customers", 'customers' in g and g['customers'], str(g))

print("\n== placing a new multi-item order ==")
user = dict(db.get_user_by_email('jela@stevens.edu'))
before_balance = float(user['balance_owed'])
cart = [
    {'name':'PHAZE II','sku':'BBMVP2','unit_price':150.0,'quantity':2,
     'option_type':'Weight','option_value':'15 lb','product_type':'bowling_ball','note':'drill later'},
    {'name':'GRIP SACK','sku':'AC992','unit_price':5.5,'quantity':1,
     'option_type':'','option_value':'','product_type':'general','note':''},
]
new_id = db.place_order_items(user, cart, checkout_note='leave at the desk')
check("place_order_items returns an order id", isinstance(new_id, int) and new_id > 0, str(new_id))
placed = db.get_order(new_id)
check("new order holds both lines", len(placed['items']) == 2, str(len(placed['items'])))
check("order total = 2*150 + 5.50", abs(float(placed['total_price']) - 305.5) < 0.01,
      str(placed['total_price']))
check("checkout note stored on the order, not each item",
      placed['note'] == 'leave at the desk', repr(placed['note']))
check("item note kept on its item",
      any(i['note'] == 'drill later' for i in placed['items']))
after = float(dict(db.get_user_by_email('jela@stevens.edu'))['balance_owed'])
check("balance increased by the order total", abs(after - (before_balance + 305.5)) < 0.01,
      f"{before_balance} -> {after}")

print("\n== one email per order, not per item ==")
import email_utils
sent = []
email_utils.send_email = lambda subject, body, to: sent.append((subject, body, to))
db.update_order_status(new_id, 'approved')
check("a 2-item order sent exactly 1 email", len(sent) == 1, f"{len(sent)} emails")
if sent:
    body = sent[0][1]
    check("email lists both products", 'PHAZE II' in body and 'GRIP SACK' in body)
    check("email shows the order total", '305.50' in body, body[:400])
    check("email shows per-line quantities", '2 x PHAZE II' in body, body[:400])
    check("subject names the order", f'#{new_id}' in sent[0][0], sent[0][0])

sent.clear()
db.update_all_orders_status([new_id], 'ordered')
check("bulk update also sends 1 email for that order", len(sent) == 1, f"{len(sent)}")

print("\n== deleting an order removes its items and refunds the balance ==")
before_del = float(dict(db.get_user_by_email('jela@stevens.edu'))['balance_owed'])
db.delete_order(new_id)
check("order gone", db.get_order(new_id) is None)
con = sqlite3.connect(DB)
check("its items gone too",
      con.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (new_id,)).fetchone()[0] == 0)
con.close()
after_del = float(dict(db.get_user_by_email('jela@stevens.edu'))['balance_owed'])
check("balance reduced by the order total", abs(after_del - (before_del - 305.5)) < 0.01,
      f"{before_del} -> {after_del}")

print("\n== dashboard data still assembles ==")
data = db.get_owner_dashboard_data(['submitted','approved','ordered','fulfilled'])
check("dashboard returns orders with items",
      all('items' in o for o in data['orders']), str(len(data['orders'])))
check("dashboard order count", len(data['orders']) == 3, str(len(data['orders'])))

print("\n== re-running migrations is a no-op ==")
db._run_migrations_once.clear()
db.init_db()
con = sqlite3.connect(DB)
check("still 3 orders after a second migration run",
      con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3)
check("still 5 items", con.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 5)
con.close()

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
