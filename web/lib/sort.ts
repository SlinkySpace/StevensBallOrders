import type { Product } from './api'

export type Sort = 'default' | 'price-asc' | 'price-desc' | 'name' | 'sku'

export const SORTS: { value: Sort; label: string }[] = [
  { value: 'default', label: 'Default order' },
  { value: 'price-asc', label: 'Price · low to high' },
  { value: 'price-desc', label: 'Price · high to low' },
  { value: 'name', label: 'Name · A to Z' },
  { value: 'sku', label: 'SKU · A to Z' },
]

/**
 * Order the filtered catalog.
 *
 * "Default" is the order the API sends - category, sub-category, then name -
 * which is how the team already thinks about the catalog, so it stays the
 * default and is returned untouched.
 *
 * Products with no price or no SKU sort last whatever the key, and whichever
 * way price runs. A product reads $0.00 when the scrape could not find a price,
 * and those belong at the bottom of "high to low" every bit as much as at the
 * bottom of "low to high" - so the direction flips the comparison between two
 * real prices, rather than negating the whole ordering and floating the
 * priceless rows to the top.
 *
 * Names and SKUs compare through Intl.Collator with numeric ordering,
 * so "!Q Tour 78/U" and "3-BALL TOTE" land where a reader expects and
 * "Pad 10" follows "Pad 9" rather than preceding it.
 */
export function sortProducts(rows: Product[], sort: Sort): Product[] {
  if (sort === 'default') return rows

  const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true })

  // Array.prototype.sort is stable, so ties keep the catalog's own order.
  return [...rows].sort((a, b) => {
    if (sort === 'price-asc' || sort === 'price-desc') {
      const left = Number(a.price) || 0
      const right = Number(b.price) || 0
      // Ahead of the flip, so it holds in both directions.
      if (left <= 0 || right <= 0) return (left <= 0 ? 1 : 0) - (right <= 0 ? 1 : 0)
      return sort === 'price-desc' ? right - left : left - right
    }
    if (sort === 'sku') {
      const left = String(a.sku ?? '').trim()
      const right = String(b.sku ?? '').trim()
      if (!left || !right) return (left ? 0 : 1) - (right ? 0 : 1)
      return collator.compare(left, right)
    }
    return collator.compare(a.name ?? '', b.name ?? '')
  })
}
