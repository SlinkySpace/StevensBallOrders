import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from config import DATABASE_URL, DB_PATH, BALL_BATCH_THRESHOLD, BALL_PENDING_STATUSES
from email_utils import maybe_send_ball_batch_email, send_order_status_email

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    saved_card TEXT DEFAULT '',
    balance_owed REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    customer_first_name TEXT NOT NULL,
    customer_last_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
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
    status TEXT NOT NULL DEFAULT 'submitted',
    timestamp TEXT NOT NULL,
    main_category TEXT DEFAULT '',
    sub_category TEXT DEFAULT '',
    product_type TEXT DEFAULT '',
    FOREIGN KEY(user_id) REFERENCES users(id)
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
"""


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    saved_card TEXT DEFAULT '',
    balance_owed DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    customer_first_name TEXT NOT NULL,
    customer_last_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
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
    status TEXT NOT NULL DEFAULT 'submitted',
    timestamp TEXT NOT NULL,
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
"""


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def get_conn():
    if USE_POSTGRES:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
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


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(POSTGRES_SCHEMA if USE_POSTGRES else SQLITE_SCHEMA)


def create_user(first_name: str, last_name: str, email: str):
    try:
        with get_conn() as conn:
            conn.execute(
                f"INSERT INTO users(first_name, last_name, email, created_at) VALUES ({_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()})",
                (first_name.strip(), last_name.strip(), email.strip().lower(), now_iso()),
            )
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "duplicate" in msg:
            return False
        raise


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


def place_order_items(user: dict, cart_items: list[dict], checkout_note: str = '') -> None:
    total_to_add = 0.0
    with get_conn() as conn:
        for item in cart_items:
            quantity = int(item.get('quantity', 1) or 1)
            unit_price = float(item.get('unit_price', 0) or 0)
            total_price = round(quantity * unit_price, 2)
            total_to_add += total_price

            item_note = str(item.get('note', '') or '').strip()
            checkout_note_clean = str(checkout_note or '').strip()
            merged_note = item_note
            if checkout_note_clean:
                merged_note = f"{item_note} | Checkout: {checkout_note_clean}" if item_note else f"Checkout: {checkout_note_clean}"

            conn.execute(
                f"""
                INSERT INTO orders(
                    user_id, customer_first_name, customer_last_name, customer_email,
                    product_name, sku, option_type, option_value, quantity, unit_price,
                    total_price, image_url, product_url, note, status, timestamp,
                    main_category, sub_category, product_type
                )
                VALUES (
                    {_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()},
                    {_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()},
                    {_placeholder()}, {_placeholder()}, {_placeholder()}, {_placeholder()},
                    {_placeholder()}, {_placeholder()}, 'submitted', {_placeholder()},
                    {_placeholder()}, {_placeholder()}, {_placeholder()}
                )
                """,
                (
                    user['id'],
                    user['first_name'],
                    user['last_name'],
                    user['email'],
                    str(item.get('name', '')),
                    str(item.get('sku', '')),
                    str(item.get('option_type', '')),
                    str(item.get('option_value', '')),
                    quantity,
                    unit_price,
                    total_price,
                    str(item.get('image_url', '')),
                    str(item.get('product_url', '')),
                    merged_note,
                    now_iso(),
                    str(item.get('main_category', '')),
                    str(item.get('sub_category', '')),
                    str(item.get('product_type', '')),
                ),
            )

        conn.execute(
            f"UPDATE users SET balance_owed = balance_owed + {_placeholder()} WHERE id = {_placeholder()}",
            (round(total_to_add, 2), user['id']),
        )

    clear_saved_cart(int(user["id"]))
    evaluate_ball_batch_notification()


def get_orders_for_user(user_id: int, statuses: Optional[Iterable[str]] = None):
    query = f"SELECT * FROM orders WHERE user_id = {_placeholder()}"
    params = [user_id]

    if statuses:
        statuses = list(statuses)
        query += f" AND status IN ({_placeholders(len(statuses))})"
        params.extend(statuses)

    query += " ORDER BY timestamp DESC, id DESC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return rows


def get_all_orders(statuses: Optional[Iterable[str]] = None):
    query = "SELECT * FROM orders"
    params = []

    if statuses:
        statuses = list(statuses)
        query += f" WHERE status IN ({_placeholders(len(statuses))})"
        params.extend(statuses)

    query += " ORDER BY timestamp DESC, id DESC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return rows


def update_order_status(order_id: int, new_status: str) -> None:
    with get_conn() as conn:
        order = conn.execute(
            f"SELECT * FROM orders WHERE id = {_placeholder()}",
            (order_id,),
        ).fetchone()
        if not order:
            return

        conn.execute(
            f"UPDATE orders SET status = {_placeholder()} WHERE id = {_placeholder()}",
            (new_status, order_id),
        )
        order['status'] = new_status

    if new_status in {'approved', 'ordered', 'fulfilled'}:
        send_order_status_email(order, new_status)
    evaluate_ball_batch_notification()


def update_all_orders_status(order_ids: Iterable[int], new_status: str) -> None:
    ids = [int(x) for x in order_ids]
    if not ids:
        return

    placeholders = _placeholders(len(ids))

    with get_conn() as conn:
        affected_orders = conn.execute(
            f"SELECT * FROM orders WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

        if not affected_orders:
            return

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

        conn.execute(
            f"DELETE FROM orders WHERE id = {_placeholder()}",
            (order_id,),
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


def get_pending_ball_orders_count() -> int:
    placeholders = _placeholders(len(BALL_PENDING_STATUSES))

    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(quantity), 0) AS total_count
            FROM orders
            WHERE product_type = 'bowling_ball'
              AND status IN ({placeholders})
            """,
            tuple(BALL_PENDING_STATUSES),
        ).fetchone()

    return int(row['total_count'] or 0)


def get_grouped_pending_ball_orders():
    placeholders = _placeholders(len(BALL_PENDING_STATUSES))

    if USE_POSTGRES:
        query = f"""
            SELECT
                product_name,
                sku,
                option_value,
                SUM(quantity) AS total_qty,
                STRING_AGG(customer_first_name || ' ' || customer_last_name, ', ' ORDER BY customer_first_name, customer_last_name) AS customers
            FROM orders
            WHERE product_type = 'bowling_ball'
              AND status IN ({placeholders})
            GROUP BY product_name, sku, option_value
            ORDER BY product_name, option_value
        """
    else:
        query = f"""
            SELECT
                product_name,
                sku,
                option_value,
                SUM(quantity) AS total_qty,
                GROUP_CONCAT(customer_first_name || ' ' || customer_last_name, ', ') AS customers
            FROM orders
            WHERE product_type = 'bowling_ball'
              AND status IN ({placeholders})
            GROUP BY product_name, sku, option_value
            ORDER BY product_name, option_value
        """

    with get_conn() as conn:
        rows = conn.execute(query, tuple(BALL_PENDING_STATUSES)).fetchall()

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


def evaluate_ball_batch_notification() -> None:
    current_count = get_pending_ball_orders_count()
    last_notified = int(_get_app_state('last_ball_batch_notified_count', '0') or 0)

    if current_count >= BALL_BATCH_THRESHOLD and current_count != last_notified:
        maybe_send_ball_batch_email(current_count)
        _set_app_state('last_ball_batch_notified_count', str(current_count))
    elif current_count < BALL_BATCH_THRESHOLD and last_notified != 0:
        _set_app_state('last_ball_batch_notified_count', '0')
