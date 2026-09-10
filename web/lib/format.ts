import type { CartLine, Order, Product } from './api'

export function currency(value: number | string | null | undefined): string {
  const amount = Number(value ?? 0)
  return `$${amount.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Catalog images live in the Python app's static/ directory, committed there by
 * the refresh workflow, and are served by a route handler rather than copied -
 * one set of files, owned by the scraper.
 */
export function imageSrc(stored: string | null | undefined): string | null {
  const value = String(stored ?? '').trim().split('\\').join('/')
  if (!value) return null
  if (/^(https?:|data:)/.test(value)) return value
  if (value.startsWith('static/')) return '/' + value
  return null
}

export function initials(first: string, last: string): string {
  return `${first?.[0] ?? ''}${last?.[0] ?? ''}`.toUpperCase() || '?'
}

export function pillClass(status: string): string {
  const known = ['submitted', 'approved', 'ordered', 'fulfilled', 'cancelled']
  const key = String(status || '').toLowerCase()
  return `pill pill--${known.includes(key) ? key : 'submitted'}`
}

/** "2026-09-06T22:12:43 · 2 items" — the meta line under an order heading. */
export function orderMeta(order: Order): string {
  const when = String(order.timestamp || '').replace('T', ' ').slice(0, 16)
  const count = order.item_count ?? 0
  return `${when} · ${count} item${count === 1 ? '' : 's'}`
}

export function lineTotal(line: CartLine): number {
  return Number(line.unit_price || 0) * Number(line.quantity || 0)
}

export function cartTotal(lines: CartLine[]): number {
  return lines.reduce((sum, line) => sum + lineTotal(line), 0)
}

export function cartUnits(lines: CartLine[]): number {
  return lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0)
}

/** The one-line description under a product name in the cart and popover. */
export function productMeta(product: Product | CartLine): string {
  const parts: string[] = []
  const sku = String(product.sku ?? '').trim()
  parts.push(sku ? `SKU ${sku}` : 'No SKU')

  const scent = String((product as Product).scent ?? '').trim()
  if (scent && scent.toLowerCase() !== 'none') parts.push(`Scent · ${scent}`)

  const price = 'price' in product ? product.price : product.unit_price
  parts.push(`${currency(price)} each`)
  return parts.join('  ·  ')
}

/**
 * Bowling balls default to 15 lb, which is what most of the team throws.
 * Everything else takes the first option.
 */
export function defaultOption(product: Product): string {
  if (!product.options?.length) return ''
  if (product.product_type === 'bowling_ball') {
    const fifteen = product.options.find((o) => o.replace(/\D/g, '') === '15')
    if (fifteen) return fifteen
  }
  return product.options[0]
}

export function ordersToCsv(orders: Order[]): string {
  const header = [
    'order_id', 'ordered', 'status', 'customer', 'product', 'sku', 'option',
    'quantity', 'unit_price', 'line_total', 'order_note',
  ]
  const rows = [header.join(',')]

  const escape = (value: unknown) => {
    const text = String(value ?? '')
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }

  for (const order of orders) {
    for (const item of order.items ?? []) {
      rows.push([
        order.id,
        order.timestamp,
        order.status,
        `${order.customer_first_name} ${order.customer_last_name}`,
        item.product_name,
        item.sku,
        item.option_value,
        item.quantity,
        item.unit_price,
        item.total_price,
        order.note,
      ].map(escape).join(','))
    }
  }
  return rows.join('\n')
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
