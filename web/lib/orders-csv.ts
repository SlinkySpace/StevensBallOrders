// Types only, so this module pulls in nothing at runtime and the tests can run
// straight off the source with node --experimental-strip-types.
import type { Order, OrderItem } from './api.ts'

/**
 * Orders as the CSV the Eboard actually places with Storm.
 *
 * The shape follows the sheet that was being kept by hand: one row per item
 * with the person's name repeated down the rows, a subtotal row closing each
 * person out, and a blank row between people. Grouping by person is the point -
 * one person's gear has to be picked, paid for and handed over together, and
 * the flat per-order export made that a sorting job every time.
 *
 * Price is the line total, not the unit price. That is what the sheet holds
 * (two Abralon pads at 2.89 read as 5.78) and it is what has to add up to the
 * subtotal.
 */

export const ORDER_CSV_HEADER = [
  'Name', 'Item', 'Notes', 'Quantity', 'Link', 'Price', 'Total',
] as const

const COLUMNS = ORDER_CSV_HEADER.length

function escape(value: unknown): string {
  const text = String(value ?? '')
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** Money in whole cents, so a column of them can be summed without drift. */
function cents(value: unknown): number {
  return Math.round((Number(value) || 0) * 100)
}

/**
 * Cents back to what the sheet holds: a plain number, no currency symbol and no
 * trailing zeros - 120, 9.9, 365.38. Excel writes them that way under General
 * formatting, and a bare number is what anything downstream can add up.
 */
function money(inCents: number): string {
  return String(Number((inCents / 100).toFixed(2)))
}

/** The weight and any note the person left, in the one cell the sheet gives. */
function notesFor(item: OrderItem): string {
  return [item.option_value, item.note]
    .map((part) => String(part ?? '').trim())
    .filter(Boolean)
    .join(' - ')
}

function row(cells: unknown[]): string {
  const padded = [...cells]
  while (padded.length < COLUMNS) padded.push('')
  return padded.map(escape).join(',')
}

/** Keeps every row the same width, so the gap reads as a row and not as EOF. */
const BLANK_ROW = row([])

type Group = { name: string; items: OrderItem[] }

export function ordersToCsv(orders: Order[]): string {
  // Keyed on email because that is the identity - two people on a team can
  // share a first name, and a rename between orders should not split someone
  // into two blocks. Insertion order is kept, so the export follows whatever
  // order the page was already showing rather than imposing its own.
  const groups = new Map<string, Group>()

  for (const order of orders ?? []) {
    const name = `${order.customer_first_name ?? ''} ${order.customer_last_name ?? ''}`.trim()
    const key = String(order.customer_email ?? '').trim().toLowerCase() || name.toLowerCase()
    if (!key) continue

    const group = groups.get(key) ?? { name, items: [] }
    // An order placed before a name change still names the person as they are
    // now, rather than keeping whichever spelling happened to come first.
    group.name = name || group.name
    group.items.push(...(order.items ?? []))
    groups.set(key, group)
  }

  const rows = [ORDER_CSV_HEADER.join(',')]

  for (const group of groups.values()) {
    if (!group.items.length) continue        // nothing to pick, nothing to show
    if (rows.length > 1) rows.push(BLANK_ROW)

    let total = 0
    for (const item of group.items) {
      const line = cents(item.total_price)
      total += line
      rows.push(row([
        group.name,
        item.product_name,
        notesFor(item),
        item.quantity,
        item.product_url,
        money(line),
        '',                                  // Total is the subtotal row's
      ]))
    }

    rows.push(row([group.name, '', '', '', '', '', money(total)]))
  }

  // Trailing newline, which is both the usual convention for a text file and
  // what Python's csv.writer emits - app.py's export is byte-identical for the
  // same orders, and a test there would catch it drifting.
  return `${rows.join('\n')}\n`
}
