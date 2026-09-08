/**
 * Read-only data access against the same Neon database the Streamlit app uses.
 *
 * READ ONLY, ON PURPOSE. This proof exists to show the catalog and real orders
 * rendering outside Streamlit while the Streamlit app stays live and keeps
 * serving the team. Nothing here writes, and scripts/assert-read-only.mjs fails
 * the build if a write statement appears.
 *
 * The queries mirror db.py so the two agree on what a row means - same
 * ordering, same visible/in-stock filters, same shape of an order with its
 * items attached.
 */

import { neon } from '@neondatabase/serverless'

if (!process.env.DATABASE_URL) {
  throw new Error(
    'DATABASE_URL is not set. Copy it from .streamlit/secrets.toml into web/.env.local.',
  )
}

// Neon's HTTP driver: one request per query, no pool to keep warm. That is the
// right shape for serverless, where db.py's cached psycopg pool would not
// survive between invocations anyway.
const sql = neon(process.env.DATABASE_URL)

export type Product = {
  id: number
  product_url: string
  sku: string
  name: string
  price: number
  in_stock: boolean
  is_visible: boolean
  main_category: string
  sub_category: string
  product_type: string
  scent: string
  image_url: string
  updated_at: string
  updated_by: string
}

export type OrderItem = {
  id: number
  order_id: number
  product_name: string
  sku: string
  option_type: string
  option_value: string
  quantity: number
  unit_price: number
  total_price: number
  image_url: string
  product_url: string
  note: string
}

export type Order = {
  id: number
  user_id: number
  customer_first_name: string
  customer_last_name: string
  customer_email: string
  note: string
  total_price: number
  status: string
  timestamp: string
  items: OrderItem[]
  item_count: number
}

export type User = {
  id: number
  first_name: string
  last_name: string
  email: string
  balance_owed: number
  created_at: string
  password_hash: string
}

/** Mirrors db.get_products(visible_only, in_stock_only). */
export async function getProducts(
  opts: { visibleOnly?: boolean; inStockOnly?: boolean } = {},
): Promise<Product[]> {
  const { visibleOnly = false, inStockOnly = false } = opts
  // Written as whole statements rather than a built string so the tagged
  // template still parameterises, and so the read-only check can see them.
  if (visibleOnly && inStockOnly) {
    return (await sql`SELECT * FROM products WHERE is_visible = TRUE AND in_stock = TRUE
                      ORDER BY main_category, sub_category, name`) as Product[]
  }
  if (visibleOnly) {
    return (await sql`SELECT * FROM products WHERE is_visible = TRUE
                      ORDER BY main_category, sub_category, name`) as Product[]
  }
  return (await sql`SELECT * FROM products
                    ORDER BY main_category, sub_category, name`) as Product[]
}

export async function countProducts(): Promise<number> {
  const rows = (await sql`SELECT COUNT(*)::int AS n FROM products`) as { n: number }[]
  return rows[0]?.n ?? 0
}

/** Mirrors db.get_user_by_email. Includes password_hash - callers must not leak it. */
export async function getUserByEmail(email: string): Promise<User | null> {
  const rows = (await sql`SELECT * FROM users WHERE LOWER(email) = LOWER(${email.trim()})
                          LIMIT 1`) as User[]
  return rows[0] ?? null
}

/** Mirrors db.get_orders_for_user, including _attach_items. */
export async function getOrdersForUser(userId: number): Promise<Order[]> {
  const orders = (await sql`SELECT * FROM orders WHERE user_id = ${userId}
                            ORDER BY timestamp DESC, id DESC`) as Order[]
  return attachItems(orders)
}

/** Mirrors db.get_all_orders. */
export async function getAllOrders(): Promise<Order[]> {
  const orders = (await sql`SELECT * FROM orders
                            ORDER BY timestamp DESC, id DESC`) as Order[]
  return attachItems(orders)
}

async function attachItems(orders: Order[]): Promise<Order[]> {
  if (orders.length === 0) return []
  const ids = orders.map((o) => o.id)
  // One query for every order's items, then grouped in memory - the same thing
  // _attach_items does, and for the same reason: one round trip, not N.
  const items = (await sql`SELECT * FROM order_items WHERE order_id = ANY(${ids})
                           ORDER BY id`) as OrderItem[]

  const byOrder = new Map<number, OrderItem[]>()
  for (const item of items) {
    const list = byOrder.get(item.order_id)
    if (list) list.push(item)
    else byOrder.set(item.order_id, [item])
  }

  return orders.map((order) => {
    const own = byOrder.get(order.id) ?? []
    return {
      ...order,
      items: own,
      item_count: own.reduce((sum, i) => sum + Number(i.quantity ?? 0), 0),
    }
  })
}

/** Distinct categories, for the catalog filters. */
export async function getCategories(): Promise<{ main: string[]; sub: string[] }> {
  const rows = (await sql`SELECT DISTINCT main_category, sub_category FROM products
                          WHERE is_visible = TRUE
                          ORDER BY main_category, sub_category`) as
    { main_category: string; sub_category: string }[]
  return {
    main: [...new Set(rows.map((r) => r.main_category).filter(Boolean))],
    sub: [...new Set(rows.map((r) => r.sub_category).filter(Boolean))],
  }
}

/** Mirrors db.get_catalog_freshness - when the catalog was last synced. */
export async function getCatalogFreshness(): Promise<{ value: string } | null> {
  const rows = (await sql`SELECT value FROM app_state WHERE key = 'catalog_last_import'
                          LIMIT 1`) as { value: string }[]
  return rows[0] ?? null
}

/**
 * Shape of every stored password hash, with no hash, email or password in the
 * result - only what is needed to prove the Node verifier can read them.
 *
 * This is how the proof answers "will the team still be able to log in?"
 * without handling anyone's credentials: if every stored hash parses into the
 * algorithm, iteration count and field lengths verifyPassword() expects, then
 * verification is a pure function of inputs it already handles correctly (see
 * scripts/password-compat.test.ts).
 */
export async function getPasswordHashShapes(): Promise<
  { hasPassword: boolean; algorithm: string; iterations: number; saltBytes: number; digestBytes: number }[]
> {
  const rows = (await sql`SELECT password_hash FROM users
                          ORDER BY id`) as { password_hash: string | null }[]

  return rows.map((row) => {
    const stored = String(row.password_hash ?? '')
    if (!stored) {
      return { hasPassword: false, algorithm: '', iterations: 0, saltBytes: 0, digestBytes: 0 }
    }
    const parts = stored.split('$')
    if (parts.length !== 4) {
      return { hasPassword: true, algorithm: '(unparseable)', iterations: 0, saltBytes: 0, digestBytes: 0 }
    }
    const [algorithm, iterations, saltB64, digestB64] = parts
    return {
      hasPassword: true,
      algorithm,
      iterations: Number.parseInt(iterations, 10) || 0,
      saltBytes: Buffer.from(saltB64, 'base64').length,
      digestBytes: Buffer.from(digestB64, 'base64').length,
    }
  })
}
