/**
 * The only way this app reaches the database.
 *
 * Everything goes through the Python API, which owns db.py - so there is one
 * implementation of upsert_products, place_order_items and the rest, and this
 * side cannot drift from it on the code that deletes rows and charges people.
 *
 * `credentials: 'include'` on every call: the session is an HttpOnly cookie the
 * API sets, and cross-origin fetches drop cookies unless asked not to.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, '') || 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    })
  } catch {
    throw new ApiError(
      `Could not reach the API at ${API_BASE}. Is it running?`, 0,
    )
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }

  if (!response.ok) {
    // FastAPI puts the message in `detail`; fall back to the raw body so a
    // proxy error or an HTML error page is still legible.
    const detail =
      (body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : '') || text.slice(0, 200) || response.statusText
    throw new ApiError(detail, response.status)
  }

  return body as T
}

// --- types ----------------------------------------------------------------

export type User = {
  id: number
  first_name: string
  last_name: string
  email: string
  balance_owed: number
  saved_card?: string
}

export type Product = {
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
  option_type: string
  options: string[]
}

export type CartLine = {
  product_url: string
  name: string
  sku: string
  unit_price: number
  quantity: number
  option_type: string
  option_value: string
  note: string
  image_url: string
  product_type: string
  scent?: string
}

export type OrderItem = {
  id: number
  product_name: string
  sku: string
  option_type: string
  option_value: string
  quantity: number
  unit_price: number
  total_price: number
  note: string
}

export type Order = {
  id: number
  customer_first_name: string
  customer_last_name: string
  customer_email: string
  note: string
  total_price: number
  status: string
  timestamp: string
  item_count: number
  items: OrderItem[]
}

export type TeamUser = User & { has_password: boolean; created_at: string }

export type Dashboard = {
  orders: Order[]
  users: TeamUser[]
  pending_ball_count: number
  active_order_count: number
  grouped_balls: {
    product_name: string; sku: string; option_value: string
    total_qty: number; customers: string
  }[]
  statuses: string[]
  ball_batch_threshold: number
}

export type Freshness = {
  age: string
  age_days: number
  stale: boolean
  stale_after_days: number
  total_products: number
  last_import: { at?: string; mode?: string; count?: number } | null
}

// --- calls ----------------------------------------------------------------

export const api = {
  me: () => request<{ user: User | null; is_admin: boolean }>('/api/auth/me'),

  login: (email: string, password: string) =>
    request<{ user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  signup: (payload: {
    first_name: string; last_name: string; email: string
    password: string; confirm: string; access_code: string
  }) =>
    request<{ user: User }>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  claim: (payload: { email: string; password: string; confirm: string; access_code: string }) =>
    request<{ user: User }>('/api/auth/claim', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  logout: () => request<{ ok: true }>('/api/auth/logout', { method: 'POST' }),

  changePassword: (current_password: string, new_password: string, confirm: string) =>
    request<{ ok: true }>('/api/auth/password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password, confirm }),
    }),

  products: () =>
    request<{ products: Product[]; main_categories: string[]; sub_categories: string[] }>(
      '/api/products',
    ),

  freshness: () => request<Freshness>('/api/catalog/freshness'),

  cart: () => request<{ cart: CartLine[] }>('/api/cart'),
  saveCart: (lines: CartLine[]) =>
    request<{ ok: true; lines: number }>('/api/cart', {
      method: 'PUT',
      body: JSON.stringify(lines),
    }),

  orders: () => request<{ orders: Order[] }>('/api/orders'),
  placeOrder: (note: string) =>
    request<{ ok: true; order_id: number }>('/api/orders', {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),

  savedCard: (saved_card: string) =>
    request<{ ok: true }>('/api/profile/saved-card', {
      method: 'POST',
      body: JSON.stringify({ saved_card }),
    }),

  dashboard: (statuses: string[]) =>
    request<Dashboard>(`/api/admin/dashboard?statuses=${encodeURIComponent(statuses.join(','))}`),

  setOrderStatus: (orderId: number, statusValue: string) =>
    request<{ ok: true }>(`/api/admin/orders/${orderId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: statusValue }),
    }),

  bulkStatus: (orderIds: number[], statusValue: string) =>
    request<{ ok: true; updated: number }>('/api/admin/orders/bulk-status', {
      method: 'POST',
      body: JSON.stringify({ order_ids: orderIds, status: statusValue }),
    }),

  deleteOrder: (orderId: number) =>
    request<{ ok: true }>(`/api/admin/orders/${orderId}`, { method: 'DELETE' }),

  setBalance: (userId: number, balance: number) =>
    request<{ ok: true }>(`/api/admin/users/${userId}/balance`, {
      method: 'POST',
      body: JSON.stringify({ balance }),
    }),

  resetPassword: (userId: number) =>
    request<{ ok: true }>(`/api/admin/users/${userId}/reset-password`, { method: 'POST' }),

  recheckBallBatch: () =>
    request<{ ok: true }>('/api/admin/recheck-ball-batch', { method: 'POST' }),
}
