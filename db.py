import json
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import streamlit as st

from config import DATABASE_URL, DB_PATH, BALL_BATCH_THRESHOLD, BALL_PENDING_STATUSES
from email_utils import maybe_send_ball_batch_email, send_order_status_email

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        # Falls back to one fresh connection per call. Works, just slower.
        ConnectionPool = None


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    saved_card TEXT DEFAULT '',
    balance_owed REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    password_hash TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    customer_first_name TEXT NOT NULL,
    customer_last_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    note TEXT DEFAULT '',
    total_price REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'submitted',
    timestamp TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    sku TEXT DEFAULT '',
    option_type TEXT DEFAULT '',
    option_value TEXT DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0,
    total_price REAL NOT NULL DEFAULT 0,
    image_url TEXT DEFAULT '',
    product_url TEXT DEFAULT '',
    note TEXT DEFAULT '',
    main_category TEXT DEFAULT '',
    sub_category TEXT DEFAULT '',
    product_type TEXT DEFAULT '',
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_carts (
    user_id INTEGER PRIMARY KEY,
    cart_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_url TEXT NOT NULL UNIQUE,
    sku TEXT DEFAULT '',
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    in_stock INTEGER NOT NULL DEFAULT 1,
    is_visible INTEGER NOT NULL DEFAULT 1,
    main_category TEXT DEFAULT '',
    sub_category TEXT DEFAULT '',
    product_type TEXT DEFAULT 'general',
    scent TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    updated_by TEXT DEFAULT ''
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    saved_card TEXT DEFAULT '',
    balance_owed DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    password_hash TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    customer_first_name TEXT NOT NULL,
    customer_last_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    note TEXT DEFAULT '',
    total_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'submitted',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    sku TEXT DEFAULT '',
    option_type TEXT DEFAULT '',
    option_value TEXT DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    image_url TEXT DEFAULT '',
    product_url TEXT DEFAULT '',
    note TEXT DEFAULT '',
    main_category TEXT DEFAULT '',
    sub_category TEXT DEFAULT '',
    product_type TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_carts (
    user_id BIGINT PRIMARY KEY REFERENCES users(id),
    cart_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    product_url TEXT NOT NULL UNIQUE,
    sku TEXT DEFAULT '',
    name TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL DEFAULT 0,
    in_stock BOOLEAN NOT NULL DEFAULT TRUE,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    main_category TEXT DEFAULT '',
    sub_category TEXT DEFAULT '',
    product_type TEXT DEFAULT 'general',
    scent TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    updated_by TEXT DEFAULT ''
);
"""

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_product_type ON order_items(product_type)",
    "CREATE INDEX IF NOT EXISTS idx_saved_carts_user_id ON saved_carts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_products_visible ON products(is_visible)",
    "CREATE INDEX IF NOT EXISTS idx_products_sub_category ON products(sub_category)",
]


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@st.cache_resource(show_spinner=False)
def _get_pool():
    """
    One shared Postgres pool for the whole server process.

    Opening a connection to a hosted Postgres costs a TLS handshake, which the
    app used to pay on every single rerun - twice, because init_db() and
    refresh_user_session() each opened their own. Reusing pooled connections
    removes that from the critical path.
    """
    if not USE_POSTGRES or ConnectionPool is None:
        return None

    pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=4,
        # Hosted Postgres (Neon in particular) drops idle connections, so
        # validate before handing one out rather than failing the rerun.
        check=ConnectionPool.check_connection,
        kwargs={'row_factory': dict_row},
        open=True,
    )
    return pool


@contextmanager
def get_conn():
    if USE_POSTGRES:
        pool = _get_pool()
        if pool is not None:
            # pool.connection() commits on clean exit, rolls back on error,
            # and returns the connection to the pool either way.
            with pool.connection() as conn:
                yield conn
            return

        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    else:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = _dict_factory
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _placeholder() -> str:
    return "%s" if USE_POSTGRES else "?"


def _placeholders(n: int) -> str:
    return ",".join([_placeholder()] * n)


def _table_columns(conn, table: str) -> set[str]:
    if USE_POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        ).fetchall()
        return {str(row['column_name']) for row in rows}
    return {str(row['name']) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn, table: str) -> bool:
    if USE_POSTGRES:
        row = conn.execute(
            "SELECT to_regclass(%s) AS reg", (f'public.{table}',)
        ).fetchone()
        return bool(row and row['reg'])
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return bool(row)


def _migrate_orders_to_line_items(conn) -> None:
    """
    Move from one-row-per-item to an order header plus order_items.

    The old table stored each cart line as its own order, which meant a status
    change emailed the customer once per item and had to be repeated for every
    line. Legacy rows carry no grouping key, but everything placed in a single
    checkout was written in one loop, so (user_id, timestamp) reconstructs the
    original baskets.

    The old table is kept as orders_legacy_backup rather than dropped.
    """
    if not _table_exists(conn, 'orders'):
        return  # fresh install; the schema below creates both tables
    if 'product_name' not in _table_columns(conn, 'orders'):
        return  # already migrated

    legacy = conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
    conn.execute("ALTER TABLE orders RENAME TO orders_legacy_backup")

    # Recreate both tables in the new shape before backfilling.
    if USE_POSTGRES:
        conn.execute(POSTGRES_SCHEMA)
    else:
        conn.executescript(SQLITE_SCHEMA)

    if not legacy:
        return

    baskets: dict[tuple, list[dict]] = {}
    for row in legacy:
        row = dict(row)
        key = (row['user_id'], str(row['timestamp']), str(row['status']))
        baskets.setdefault(key, []).append(row)

    for (user_id, timestamp, status), items in baskets.items():
        first = items[0]
        total = round(sum(float(i.get('total_price') or 0) for i in items), 2)

        conn.execute(
            f"""INSERT INTO orders(user_id, customer_first_name, customer_last_name,
                   customer_email, note, total_price, status, timestamp)
                VALUES ({_placeholders(8)})""",
            (user_id, first['customer_first_name'], first['customer_last_name'],
             first['customer_email'], '', total, status, timestamp),
        )
        order_id = conn.execute(
            f"""SELECT id FROM orders WHERE user_id = {_placeholder()}
                AND timestamp = {_placeholder()} AND status = {_placeholder()}
                ORDER BY id DESC""",
            (user_id, timestamp, status),
        ).fetchone()['id']

        for item in items:
            conn.execute(
                f"""INSERT INTO order_items(order_id, product_name, sku, option_type,
                       option_value, quantity, unit_price, total_price, image_url,
                       product_url, note, main_category, sub_category, product_type)
                    VALUES ({_placeholders(14)})""",
                (order_id, item['product_name'], item.get('sku', ''),
                 item.get('option_type', ''), item.get('option_value', ''),
                 item.get('quantity', 1), item.get('unit_price', 0),
                 item.get('total_price', 0), item.get('image_url', ''),
                 item.get('product_url', ''), item.get('note', ''),
                 item.get('main_category', ''), item.get('sub_category', ''),
                 item.get('product_type', '')),
            )

    print(f'[migration] regrouped {len(legacy)} order rows into {len(baskets)} orders; '
          'the previous table is kept as orders_legacy_backup')


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    """
    CREATE TABLE IF NOT EXISTS silently does nothing when the table already
    exists, so new columns need an explicit ALTER for databases created before
    the column was added.
    """
    if USE_POSTGRES:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        return

    existing = {row['name'] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@st.cache_resource(show_spinner=False)
def _run_migrations_once() -> bool:
    with get_conn() as conn:
        # Must run before the schema below, since it renames the old table out
        # of the way and recreates both in the new shape.
        _migrate_orders_to_line_items(conn)

        if USE_POSTGRES:
            conn.execute(POSTGRES_SCHEMA)
        else:
            # sqlite3's execute() takes a single statement; the schema is many.
            conn.executescript(SQLITE_SCHEMA)
        for stmt in INDEX_STATEMENTS:
            conn.execute(stmt)

        # Accounts created before passwords existed have an empty hash and are
        # prompted to set one on their next login rather than being locked out.
        _add_column_if_missing(conn, 'users', 'password_hash', "TEXT DEFAULT ''")
    return True


def init_db() -> None:
    """
    Create tables and indexes. app.py calls this on every rerun, so the actual
    work is cached - otherwise every keystroke in the app fired a dozen DDL
    round trips at the database.
    """
    _run_migrations_once()


def create_user(first_name: str, last_name: str, email: str, password_hash: str = ''):
    try:
        with get_conn() as conn:
            conn.execute(
                f"INSERT INTO users(first_name, last_name, email, created_at, password_hash) "
                f"VALUES ({_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()})",
                (first_name.strip(), last_name.strip(), email.strip().lower(), now_iso(), password_hash),
            )
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "duplicate" in msg:
            return False
        raise


def set_user_password(user_id: int, password_hash: str) -> None:
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET password_hash = {_placeholder()} WHERE id = {_placeholder()}",
            (password_hash, user_id),
        )


def clear_user_password(user_id: int) -> None:
    """
    Owner-initiated reset. The account keeps its orders and balance but the next
    login goes through the set-a-password flow.
    """
    set_user_password(user_id, '')


def get_user_by_email(email: str):
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT * FROM users WHERE email = {_placeholder()}",
            (email.strip().lower(),),
        ).fetchone()
    return row


def update_saved_card(user_id: int, saved_card: str) -> None:
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET saved_card = {_placeholder()} WHERE id = {_placeholder()}",
            (saved_card, user_id),
        )


def update_balance(user_id: int, new_balance: float) -> None:
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET balance_owed = {_placeholder()} WHERE id = {_placeholder()}",
            (round(float(new_balance), 2), user_id),
        )


def get_saved_cart(user_id: int) -> list[dict]:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT cart_json FROM saved_carts WHERE user_id = {_placeholder()}",
            (user_id,),
        ).fetchone()

    if not row:
        return []

    try:
        parsed = json.loads(row["cart_json"])
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def save_cart(user_id: int, cart_items: list[dict]) -> None:
    cart_json = json.dumps(cart_items)

    if USE_POSTGRES:
        query = """
            INSERT INTO saved_carts(user_id, cart_json, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                cart_json = EXCLUDED.cart_json,
                updated_at = EXCLUDED.updated_at
        """
    else:
        query = """
            INSERT INTO saved_carts(user_id, cart_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                cart_json = excluded.cart_json,
                updated_at = excluded.updated_at
        """

    with get_conn() as conn:
        conn.execute(query, (user_id, cart_json, now_iso()))


def clear_saved_cart(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM saved_carts WHERE user_id = {_placeholder()}",
            (user_id,),
        )


ORDER_ITEM_COLUMNS = (
    'product_name', 'sku', 'option_type', 'option_value', 'quantity',
    'unit_price', 'total_price', 'image_url', 'product_url', 'note',
    'main_category', 'sub_category', 'product_type',
)


def _attach_items(conn, orders: list) -> list[dict]:
    """
    Hang each order's items off it, in one extra query rather than one per order.
    """
    orders = [dict(row) for row in orders]
    if not orders:
        return orders

    ids = [int(o['id']) for o in orders]
    items = conn.execute(
        f"SELECT * FROM order_items WHERE order_id IN ({_placeholders(len(ids))}) "
        f"ORDER BY id",
        ids,
    ).fetchall()

    by_order: dict[int, list[dict]] = {order_id: [] for order_id in ids}
    for item in items:
        item = dict(item)
        by_order.setdefault(int(item['order_id']), []).append(item)

    for order in orders:
        order['items'] = by_order.get(int(order['id']), [])
        order['item_count'] = sum(int(i.get('quantity') or 0) for i in order['items'])
    return orders


def place_order_items(user: dict, cart_items: list[dict], checkout_note: str = '') -> int:
    """
    Write one order that owns every line in the cart, and return its id.
    """
    if not cart_items:
        return 0

    order_total = round(
        sum(int(i.get('quantity', 1) or 1) * float(i.get('unit_price', 0) or 0)
            for i in cart_items),
        2,
    )
    timestamp = now_iso()

    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO orders(user_id, customer_first_name, customer_last_name,
                   customer_email, note, total_price, status, timestamp)
                VALUES ({_placeholders(6)}, 'submitted', {_placeholder()})""",
            (user['id'], user['first_name'], user['last_name'], user['email'],
             str(checkout_note or '').strip(), order_total, timestamp),
        )
        order_id = int(conn.execute(
            f"""SELECT id FROM orders WHERE user_id = {_placeholder()}
                AND timestamp = {_placeholder()} ORDER BY id DESC""",
            (user['id'], timestamp),
        ).fetchone()['id'])

        for item in cart_items:
            quantity = int(item.get('quantity', 1) or 1)
            unit_price = float(item.get('unit_price', 0) or 0)
            conn.execute(
                f"""INSERT INTO order_items(order_id, product_name, sku, option_type,
                       option_value, quantity, unit_price, total_price, image_url,
                       product_url, note, main_category, sub_category, product_type)
                    VALUES ({_placeholders(14)})""",
                (order_id, str(item.get('name', '')), str(item.get('sku', '')),
                 str(item.get('option_type', '')), str(item.get('option_value', '')),
                 quantity, unit_price, round(quantity * unit_price, 2),
                 str(item.get('image_url', '')), str(item.get('product_url', '')),
                 str(item.get('note', '') or '').strip(),
                 str(item.get('main_category', '')), str(item.get('sub_category', '')),
                 str(item.get('product_type', ''))),
            )

        conn.execute(
            f"UPDATE users SET balance_owed = balance_owed + {_placeholder()} WHERE id = {_placeholder()}",
            (order_total, user['id']),
        )

    clear_saved_cart(int(user["id"]))
    evaluate_ball_batch_notification()
    return order_id


def get_orders_for_user(user_id: int, statuses: Optional[Iterable[str]] = None):
    query = f"SELECT * FROM orders WHERE user_id = {_placeholder()}"
    params = [user_id]

    if statuses:
        statuses = list(statuses)
        query += f" AND status IN ({_placeholders(len(statuses))})"
        params.extend(statuses)

    query += " ORDER BY timestamp DESC, id DESC"

    with get_conn() as conn:
        return _attach_items(conn, conn.execute(query, params).fetchall())


def get_all_orders(statuses: Optional[Iterable[str]] = None):
    query = "SELECT * FROM orders"
    params = []

    if statuses:
        statuses = list(statuses)
        query += f" WHERE status IN ({_placeholders(len(statuses))})"
        params.extend(statuses)

    query += " ORDER BY timestamp DESC, id DESC"

    with get_conn() as conn:
        return _attach_items(conn, conn.execute(query, params).fetchall())


def get_order(order_id: int) -> Optional[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM orders WHERE id = {_placeholder()}", (order_id,)
        ).fetchall()
        orders = _attach_items(conn, rows)
    return orders[0] if orders else None


def update_order_status(order_id: int, new_status: str) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM orders WHERE id = {_placeholder()}", (order_id,)
        ).fetchall()
        if not rows:
            return
        order = _attach_items(conn, rows)[0]

        conn.execute(
            f"UPDATE orders SET status = {_placeholder()} WHERE id = {_placeholder()}",
            (new_status, order_id),
        )
        order['status'] = new_status

    # One email for the whole order, however many items it holds.
    if new_status in {'approved', 'ordered', 'fulfilled'}:
        send_order_status_email(order, new_status)
    evaluate_ball_batch_notification()


def update_all_orders_status(order_ids: Iterable[int], new_status: str) -> None:
    ids = [int(x) for x in order_ids]
    if not ids:
        return

    placeholders = _placeholders(len(ids))

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM orders WHERE id IN ({placeholders})", ids
        ).fetchall()
        if not rows:
            return
        affected_orders = _attach_items(conn, rows)

        conn.execute(
            f"UPDATE orders SET status = {_placeholder()} WHERE id IN ({placeholders})",
            [new_status] + ids,
        )

    if new_status in {'approved', 'ordered', 'fulfilled'}:
        for order in affected_orders:
            order['status'] = new_status
            send_order_status_email(order, new_status)

    evaluate_ball_batch_notification()


def delete_order(order_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT user_id, total_price FROM orders WHERE id = {_placeholder()}",
            (order_id,),
        ).fetchone()

        if not row:
            return

        total_price = round(float(row.get('total_price', 0) or 0), 2)
        user_id = int(row['user_id'])

        # Explicit rather than relying on ON DELETE CASCADE, which SQLite only
        # honours when foreign_keys pragma is on.
        conn.execute(
            f"DELETE FROM order_items WHERE order_id = {_placeholder()}", (order_id,)
        )
        conn.execute(
            f"DELETE FROM orders WHERE id = {_placeholder()}", (order_id,)
        )

        conn.execute(
            f"""
            UPDATE users
            SET balance_owed = CASE
                WHEN balance_owed - {_placeholder()} < 0 THEN 0
                ELSE balance_owed - {_placeholder()}
            END
            WHERE id = {_placeholder()}
            """,
            (total_price, total_price, user_id),
        )

    evaluate_ball_batch_notification()


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY last_name, first_name, email"
        ).fetchall()
    return rows


PENDING_BALL_COUNT_QUERY_TEMPLATE = """
    SELECT COALESCE(SUM(oi.quantity), 0) AS total_count
    FROM order_items oi
    JOIN orders o ON o.id = oi.order_id
    WHERE oi.product_type = 'bowling_ball'
      AND o.status IN ({placeholders})
"""


def get_pending_ball_orders_count() -> int:
    query = PENDING_BALL_COUNT_QUERY_TEMPLATE.format(
        placeholders=_placeholders(len(BALL_PENDING_STATUSES))
    )
    with get_conn() as conn:
        row = conn.execute(query, tuple(BALL_PENDING_STATUSES)).fetchone()

    return int(row['total_count'] or 0)


def _grouped_pending_ball_query() -> str:
    placeholders = _placeholders(len(BALL_PENDING_STATUSES))

    if USE_POSTGRES:
        customers = (
            "STRING_AGG(o.customer_first_name || ' ' || o.customer_last_name, ', ' "
            "ORDER BY o.customer_first_name, o.customer_last_name)"
        )
    else:
        customers = "GROUP_CONCAT(o.customer_first_name || ' ' || o.customer_last_name, ', ')"

    return f"""
        SELECT
            oi.product_name AS product_name,
            oi.sku AS sku,
            oi.option_value AS option_value,
            SUM(oi.quantity) AS total_qty,
            {customers} AS customers
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.product_type = 'bowling_ball'
          AND o.status IN ({placeholders})
        GROUP BY oi.product_name, oi.sku, oi.option_value
        ORDER BY oi.product_name, oi.option_value
    """


def get_grouped_pending_ball_orders():
    with get_conn() as conn:
        rows = conn.execute(
            _grouped_pending_ball_query(), tuple(BALL_PENDING_STATUSES)
        ).fetchall()

    return rows


def _get_app_state(key: str, default: str = '') -> str:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT value FROM app_state WHERE key = {_placeholder()}",
            (key,),
        ).fetchone()
    return row['value'] if row else default


def _set_app_state(key: str, value: str) -> None:
    if USE_POSTGRES:
        query = """
            INSERT INTO app_state(key, value)
            VALUES (%s, %s)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """
    else:
        query = """
            INSERT INTO app_state(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """

    with get_conn() as conn:
        conn.execute(query, (key, value))


# Products whose URL is not a Storm one were added by hand in the Catalog
# Manager and are never touched by a scrape.
STORM_URL_MARKER = 'stormbowling.com'

PRODUCT_COLUMNS = (
    'product_url', 'sku', 'name', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'scent', 'image_url',
)

# Fields the scraper owns. A 'refresh' import overwrites these and leaves
# everything else (notably is_visible) alone.
SCRAPED_PRODUCT_COLUMNS = (
    'sku', 'name', 'price', 'in_stock', 'main_category',
    'sub_category', 'product_type', 'scent', 'image_url',
)

# Columns update_products() will write. The Catalog Manager grid exposes most of
# them; image_url is here so cleanup tools can clear a placeholder, and because
# it is the only way to give a product a picture Storm does not host. The grid
# itself keeps it read-only.
EDITABLE_PRODUCT_COLUMNS = (
    'name', 'sku', 'price', 'in_stock', 'is_visible',
    'main_category', 'sub_category', 'product_type', 'image_url',
)


def _as_bool(value) -> bool:
    """SQLite hands booleans back as 0/1, Postgres as real bools."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 't'}


def _normalize_product(row: dict) -> dict:
    row = dict(row)
    row['in_stock'] = _as_bool(row.get('in_stock'))
    row['is_visible'] = _as_bool(row.get('is_visible'))
    row['price'] = float(row.get('price') or 0)
    for key in ('product_url', 'sku', 'name', 'main_category',
                'sub_category', 'product_type', 'scent', 'image_url'):
        row[key] = str(row.get(key) or '')
    return row


def get_products(visible_only: bool = False, in_stock_only: bool = False) -> list[dict]:
    query = "SELECT * FROM products"
    clauses = []
    if visible_only:
        clauses.append("is_visible = " + ("TRUE" if USE_POSTGRES else "1"))
    if in_stock_only:
        clauses.append("in_stock = " + ("TRUE" if USE_POSTGRES else "1"))
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY main_category, sub_category, name"

    with get_conn() as conn:
        rows = conn.execute(query).fetchall()
    return [_normalize_product(row) for row in rows]


def count_products() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()
    return int(row['n'] or 0)


def get_product_urls() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT product_url FROM products").fetchall()
    return {str(row['product_url']) for row in rows}


def _usable_sku(value) -> str:
    """SKUs with whitespace are scraper junk, not real part numbers."""
    sku = str(value or '').strip().upper()
    if not sku or sku == 'NAN' or any(ch.isspace() for ch in sku):
        return ''
    return sku


def _normalized_name(value) -> str:
    """Case and punctuation folded, for comparing product names."""
    cleaned = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower())
    return ' '.join(cleaned.split())


def _rekey_to_existing(rows: list[dict]) -> list[dict]:
    """
    Point incoming rows at the product they already are.

    product_url is the table's key, but Storm moved their catalog: products that
    lived at /products/<main>/<sub>/<slug> now also appear at the site root, so
    the same grip cream arrives as /master-non-slip-grip-cream instead. Matching
    on URL alone recognised 17 of 241 scraped products; matching on SKU
    recognised 163 of 171, and those agreed on price 159 times out of 161.

    SKU is tried first. Name is the fallback, and only when the name is unique
    on both sides - without it, every product whose SKU fails to scrape arrives
    at a new URL, matches nothing, and is inserted again on every single run.
    """
    known = get_products()
    if not known:
        return rows

    def index(pairs):
        """Map key -> url, blanking any key that appears twice."""
        table: dict[str, str] = {}
        for key, url in pairs:
            if key:
                table[key] = '' if key in table else url
        return table

    by_sku = index((_usable_sku(p.get('sku')), str(p['product_url'])) for p in known)
    by_name = index((_normalized_name(p.get('name')), str(p['product_url'])) for p in known)

    # A name repeated in the incoming file is just as ambiguous as one repeated
    # in the catalog, so neither side may be relied on alone.
    incoming_names = Counter(_normalized_name(r.get('name')) for r in rows)

    known_urls = {str(p['product_url']) for p in known}
    by_sku_count = by_name_count = 0

    for row in rows:
        if row['product_url'] in known_urls:
            continue

        stored_url = by_sku.get(_usable_sku(row.get('sku')))
        if stored_url:
            row['product_url'] = stored_url
            by_sku_count += 1
            continue

        name = _normalized_name(row.get('name'))
        if name and incoming_names[name] == 1:
            stored_url = by_name.get(name)
            if stored_url:
                row['product_url'] = stored_url
                by_name_count += 1

    if by_sku_count or by_name_count:
        print(f'[catalog] matched {by_sku_count} product(s) by SKU and '
              f'{by_name_count} by name rather than URL')
    return rows


def _carry_forward(rows: list[dict], stored: list) -> list[dict]:
    """
    Apply to a replace the same field preservation a refresh gets for free.

    The ON CONFLICT clause below keeps a stored price when the scrape reports
    0, a stored category when it reports Unknown, and so on. replace deletes
    the Storm rows before inserting, so nothing ever conflicts and every one of
    those CASE WHENs is dead code. Without this, one product whose detail page
    timed out - price 0, no image - overwrites a good stored price with 0 and
    blanks its picture, where a refresh would have left both alone.

    Matched on SKU first, then URL. Storm moves product URLs, and a scrape that
    correctly adopts the new ones would otherwise look like a catalog of
    entirely new products with nothing to carry forward.
    """
    by_sku: dict[str, dict] = {}
    by_url: dict[str, dict] = {}
    for row in stored:
        row = dict(row)
        by_url[str(row['product_url'])] = row
        sku = str(row.get('sku') or '').strip().upper()
        # A SKU shared by several products identifies none of them.
        if sku:
            by_sku[sku] = None if sku in by_sku else row

    merged = []
    for row in rows:
        row = dict(row)
        sku = str(row.get('sku') or '').strip().upper()
        old = by_url.get(row['product_url']) or (by_sku.get(sku) if sku else None)
        if old:
            if float(row.get('price') or 0) <= 0:
                row['price'] = old['price']
            if not str(row.get('image_url') or '').strip():
                row['image_url'] = old['image_url']
            for col in ('main_category', 'sub_category'):
                if str(row.get(col) or '').strip() in ('', 'Unknown'):
                    row[col] = old[col]
            if str(row.get('product_type') or '') == 'general':
                row['product_type'] = old['product_type']
            # Hiding a product is a Catalog Manager decision the scrape knows
            # nothing about, so it always wins.
            row['is_visible'] = _as_bool(old['is_visible'])
        merged.append(row)
    return merged


def upsert_products(rows: list[dict], mode: str = 'refresh', updated_by: str = '') -> dict:
    """
    Load catalog rows into the products table.

    mode:
      'add_new' - only insert products that aren't already there
      'refresh' - insert new ones and overwrite scraper-owned fields on the rest,
                  preserving is_visible so hidden products stay hidden
      'replace' - clear the Storm catalog and reload it from the file, so
                  anything Storm has stopped listing disappears. Hand-added
                  products and hidden flags survive.
    """
    if mode not in {'add_new', 'refresh', 'replace'}:
        raise ValueError(f'Unknown import mode: {mode}')

    rows = [_normalize_product(row) for row in rows if str(row.get('product_url') or '').strip()]
    if not rows:
        return {'inserted': 0, 'updated': 0, 'skipped': 0, 'deleted': 0}

    if mode != 'replace':
        rows = _rekey_to_existing(rows)

    existing = set() if mode == 'replace' else get_product_urls()
    incoming = {row['product_url'] for row in rows}
    inserted = len(incoming - existing)
    matched = len(incoming & existing)

    columns = list(PRODUCT_COLUMNS) + ['updated_at', 'updated_by']
    placeholders = _placeholders(len(columns))
    now = now_iso()

    if mode == 'add_new':
        conflict = "ON CONFLICT (product_url) DO NOTHING"
    else:
        new = 'EXCLUDED' if USE_POSTGRES else 'excluded'

        def assign(col: str) -> str:
            # An out-of-stock scrape reports no price and sometimes no image.
            # Keep whatever we already know rather than zeroing it out.
            if col == 'price':
                return (f"price = CASE WHEN {new}.price > 0 "
                        f"THEN {new}.price ELSE products.price END")
            if col == 'image_url':
                return (f"image_url = CASE WHEN {new}.image_url <> '' "
                        f"THEN {new}.image_url ELSE products.image_url END")
            # Never let a scrape that could not work out a category overwrite one
            # already known good. Categories decide the weight/size selector.
            if col in ('main_category', 'sub_category'):
                return (f"{col} = CASE WHEN {new}.{col} <> '' AND {new}.{col} <> 'Unknown' "
                        f"THEN {new}.{col} ELSE products.{col} END")
            if col == 'product_type':
                return (f"product_type = CASE WHEN {new}.product_type <> 'general' "
                        f"THEN {new}.product_type ELSE products.product_type END")
            return f"{col} = {new}.{col}"

        assignments = ', '.join(assign(col) for col in SCRAPED_PRODUCT_COLUMNS)
        conflict = (
            f"ON CONFLICT (product_url) DO UPDATE SET {assignments}, "
            f"updated_at = {new}.updated_at, updated_by = {new}.updated_by"
        )

    query = (
        f"INSERT INTO products({', '.join(columns)}) "
        f"VALUES ({placeholders}) {conflict}"
    )
    deleted = 0
    with get_conn() as conn:
        if mode == 'replace':
            # Clear the Storm catalog so it mirrors the file exactly, including
            # dropping anything Storm has discontinued.
            #
            # Products added by hand are kept. They are identified by their URL
            # not being a stormbowling.com one, they never appear in a scrape,
            # and deleting the club's own shirts and raffle items on every sync
            # is not what replacing Storm's catalog means.
            #
            # Read the rows before dropping them: whatever this scrape could
            # not work out - a price, a category, the hidden flag - is carried
            # onto the replacements, which is what ON CONFLICT does for a
            # refresh and cannot do here. The select, the delete and the insert
            # share one transaction, so a failed insert takes the delete with
            # it rather than leaving the storefront empty.
            stored = conn.execute(
                f"SELECT {', '.join(PRODUCT_COLUMNS)} FROM products "
                f"WHERE product_url LIKE {_placeholder()}",
                (f'%{STORM_URL_MARKER}%',),
            ).fetchall()
            deleted = len(stored)
            rows = _carry_forward(rows, stored)

            conn.execute(
                f"DELETE FROM products WHERE product_url LIKE {_placeholder()}",
                (f'%{STORM_URL_MARKER}%',),
            )

        params = [
            tuple([row[col] for col in PRODUCT_COLUMNS] + [now, updated_by])
            for row in rows
        ]
        cur = conn.cursor()
        cur.executemany(query, params)

    return {
        'inserted': inserted if mode != 'replace' else len(rows),
        'updated': matched if mode == 'refresh' else 0,
        'skipped': matched if mode == 'add_new' else 0,
        'deleted': deleted,
    }


def update_products(updates: list[dict], updated_by: str = '') -> int:
    """
    Apply per-product edits. Each dict needs a product_url plus any subset of
    EDITABLE_PRODUCT_COLUMNS.
    """
    applied = 0
    now = now_iso()

    with get_conn() as conn:
        for update in updates:
            product_url = str(update.get('product_url') or '').strip()
            if not product_url:
                continue

            fields = {k: v for k, v in update.items() if k in EDITABLE_PRODUCT_COLUMNS}
            if not fields:
                continue

            if 'in_stock' in fields:
                fields['in_stock'] = _as_bool(fields['in_stock'])
            if 'is_visible' in fields:
                fields['is_visible'] = _as_bool(fields['is_visible'])
            if 'price' in fields:
                fields['price'] = round(float(fields['price'] or 0), 2)

            assignments = ', '.join(f"{col} = {_placeholder()}" for col in fields)
            conn.execute(
                f"UPDATE products SET {assignments}, updated_at = {_placeholder()}, "
                f"updated_by = {_placeholder()} WHERE product_url = {_placeholder()}",
                tuple(fields.values()) + (now, updated_by, product_url),
            )
            applied += 1

    return applied


def set_products_stock(product_urls: Iterable[str], in_stock: bool, updated_by: str = '') -> int:
    urls = [str(u).strip() for u in product_urls if str(u).strip()]
    if not urls:
        return 0

    with get_conn() as conn:
        conn.execute(
            f"UPDATE products SET in_stock = {_placeholder()}, updated_at = {_placeholder()}, "
            f"updated_by = {_placeholder()} WHERE product_url IN ({_placeholders(len(urls))})",
            [bool(in_stock), now_iso(), updated_by] + urls,
        )
    return len(urls)


def delete_products(product_urls: Iterable[str]) -> int:
    urls = [str(u).strip() for u in product_urls if str(u).strip()]
    if not urls:
        return 0

    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM products WHERE product_url IN ({_placeholders(len(urls))})",
            urls,
        )
    return len(urls)


CATALOG_LAST_IMPORT_KEY = 'catalog_last_import'


def record_catalog_import(mode: str, count: int, updated_by: str = '') -> None:
    _set_app_state(
        CATALOG_LAST_IMPORT_KEY,
        json.dumps({'at': now_iso(), 'mode': mode, 'count': count, 'by': updated_by}),
    )


def get_catalog_freshness() -> dict:
    """
    Signals for how current the catalog is: when a product last changed, and
    when a scraper CSV was last imported.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(updated_at) AS newest, COUNT(*) AS total FROM products"
        ).fetchone()
        state = conn.execute(
            f"SELECT value FROM app_state WHERE key = {_placeholder()}",
            (CATALOG_LAST_IMPORT_KEY,),
        ).fetchone()

    last_import = None
    if state:
        try:
            last_import = json.loads(state['value'])
        except Exception:
            last_import = None

    return {
        'last_product_change': row['newest'] if row else None,
        'total_products': int(row['total'] or 0) if row else 0,
        'last_import': last_import,
    }


def retire_missing_products(seen_urls: Iterable[str], updated_by: str = '') -> list[dict]:
    """
    Mark Storm products that were not in the latest scrape as out of stock.

    Storm drops products from its catalog and simply stops listing them. Only
    updating what the scrape contains leaves those rows behind, in stock and
    orderable forever.

    Out of stock rather than deleted, so order history keeps pointing at a real
    product and an item that returns next season comes back with its price and
    category intact. Products added by hand are left alone - they never appear
    in a Storm scrape, and retiring them would delete the club's own items on
    every sync.
    """
    seen = {str(u).strip() for u in seen_urls if str(u).strip()}

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT product_url, name, sku, price FROM products "
            f"WHERE in_stock = {'TRUE' if USE_POSTGRES else '1'}"
        ).fetchall()

    missing = [
        dict(row) for row in rows
        if STORM_URL_MARKER in str(row['product_url']).lower()
        and str(row['product_url']) not in seen
    ]
    if not missing:
        return []

    with get_conn() as conn:
        placeholders = _placeholders(len(missing))
        conn.execute(
            f"UPDATE products SET in_stock = {_placeholder()}, updated_at = {_placeholder()}, "
            f"updated_by = {_placeholder()} WHERE product_url IN ({placeholders})",
            [False, now_iso(), updated_by] + [m['product_url'] for m in missing],
        )

    return missing


def get_owner_dashboard_data(statuses: Optional[Iterable[str]] = None) -> dict:
    """
    Everything the owner dashboard renders, on a single connection.

    The dashboard used to call five separate helpers, each opening its own
    connection, on every rerun.
    """
    ball_placeholders = _placeholders(len(BALL_PENDING_STATUSES))
    grouped_query = _grouped_pending_ball_query()

    status_list = list(statuses) if statuses else None

    with get_conn() as conn:
        pending_row = conn.execute(
            PENDING_BALL_COUNT_QUERY_TEMPLATE.format(placeholders=ball_placeholders),
            tuple(BALL_PENDING_STATUSES),
        ).fetchone()

        grouped = conn.execute(grouped_query, tuple(BALL_PENDING_STATUSES)).fetchall()

        active = conn.execute(
            f"SELECT COUNT(*) AS n FROM orders WHERE status IN ({_placeholders(3)})",
            ('submitted', 'approved', 'ordered'),
        ).fetchone()

        order_query = "SELECT * FROM orders"
        order_params: list = []
        if status_list:
            order_query += f" WHERE status IN ({_placeholders(len(status_list))})"
            order_params.extend(status_list)
        order_query += " ORDER BY timestamp DESC, id DESC"
        orders = _attach_items(conn, conn.execute(order_query, order_params).fetchall())

        users = conn.execute(
            "SELECT * FROM users ORDER BY last_name, first_name, email"
        ).fetchall()

    return {
        'pending_ball_count': int(pending_row['total_count'] or 0),
        'grouped_balls': grouped,
        'active_order_count': int(active['n'] or 0),
        'orders': orders,
        'users': users,
    }


def evaluate_ball_batch_notification() -> None:
    current_count = get_pending_ball_orders_count()
    last_notified = int(_get_app_state('last_ball_batch_notified_count', '0') or 0)

    if current_count >= BALL_BATCH_THRESHOLD and current_count != last_notified:
        maybe_send_ball_batch_email(current_count)
        _set_app_state('last_ball_batch_notified_count', str(current_count))
    elif current_count < BALL_BATCH_THRESHOLD and last_notified != 0:
        _set_app_state('last_ball_batch_notified_count', '0')