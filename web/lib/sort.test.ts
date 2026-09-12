/**
 * Catalog sorting.
 *
 *   node --experimental-strip-types web/lib/sort.test.ts
 *
 * Runs against the real catalog CSV where it can find one, so the ordering is
 * checked on the names and SKUs Storm actually uses - "!Q Tour 78/U",
 * "3-BALL TOTE", "6\\\\\\" - rather than on tidy invented rows.
 */

import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sortProducts, SORTS, type Sort } from './sort.ts'
import type { Product } from './api.ts'

let passed = 0
let failed = 0

function check(label: string, ok: boolean, extra = '') {
  if (ok) { passed++; console.log(`PASS  ${label}`) }
  else { failed++; console.log(`FAIL  ${label}${extra ? `\n        ${extra}` : ''}`) }
}

function product(over: Partial<Product>): Product {
  return {
    product_url: `https://www.stormbowling.com/${over.sku ?? 'x'}`,
    sku: '', name: '', price: 0, in_stock: true, is_visible: true,
    main_category: '', sub_category: '', product_type: 'general',
    scent: '', image_url: '', option_type: '', options: [],
    ...over,
  }
}

const rows: Product[] = [
  product({ name: 'Zephyr Bag', sku: 'ZB2', price: 75 }),
  product({ name: 'apex ball', sku: 'AB1', price: 189.99 }),
  product({ name: 'Pad 10', sku: 'PD10', price: 12 }),
  product({ name: 'Pad 9', sku: 'PD9', price: 12 }),
  product({ name: 'No Price Item', sku: 'NP1', price: 0 }),
  product({ name: 'Also No Price', sku: 'NP2', price: 0 }),
  product({ name: 'No Sku Item', sku: '', price: 30 }),
]

console.log('== the four options exist ==')
check('exactly four', SORTS.length === 4, String(SORTS.length))
check('they are default, price, name, sku',
  SORTS.map((s) => s.value).join(',') === 'default,price,name,sku',
  SORTS.map((s) => s.value).join(','))

console.log('\n== default is left alone ==')
const untouched = sortProducts(rows, 'default')
check('same order', untouched.map((r) => r.sku).join() === rows.map((r) => r.sku).join())
check('same array identity (no needless copy)', untouched === rows)

console.log('\n== price, low to high ==')
const byPrice = sortProducts(rows, 'price')
const priced = byPrice.filter((r) => r.price > 0).map((r) => r.price)
check('ascending', priced.every((value, i) => i === 0 || priced[i - 1] <= value), priced.join(' '))
check('zero-price products land last',
  byPrice.slice(-2).every((r) => r.price === 0),
  byPrice.map((r) => `${r.sku}:${r.price}`).join(' '))
check('the cheapest real price is first', byPrice[0].price === 12, String(byPrice[0].price))

console.log('\n== name, A to Z ==')
const byName = sortProducts(rows, 'name')
check('case-insensitive: "apex ball" before "No Price Item"',
  byName.findIndex((r) => r.name === 'apex ball') < byName.findIndex((r) => r.name === 'No Price Item'),
  byName.map((r) => r.name).join(' | '))
check('numeric-aware: Pad 9 before Pad 10',
  byName.findIndex((r) => r.name === 'Pad 9') < byName.findIndex((r) => r.name === 'Pad 10'),
  byName.map((r) => r.name).join(' | '))
check('Zephyr Bag is last', byName[byName.length - 1].name === 'Zephyr Bag',
  byName[byName.length - 1].name)

console.log('\n== sku, A to Z ==')
const bySku = sortProducts(rows, 'sku')
check('AB1 first', bySku[0].sku === 'AB1', bySku.map((r) => r.sku).join(' '))
check('an empty SKU lands last', bySku[bySku.length - 1].sku === '',
  bySku.map((r) => r.sku || '(none)').join(' '))
check('numeric-aware: PD9 before PD10',
  bySku.findIndex((r) => r.sku === 'PD9') < bySku.findIndex((r) => r.sku === 'PD10'),
  bySku.map((r) => r.sku).join(' '))

console.log('\n== the input is never mutated ==')
const before = rows.map((r) => r.sku).join()
for (const option of SORTS) sortProducts(rows, option.value)
check('original order intact after sorting every way', rows.map((r) => r.sku).join() === before)

console.log('\n== ties keep catalog order (stable) ==')
const tied = sortProducts(rows, 'price').filter((r) => r.price === 12)
check('Pad 10 still precedes Pad 9, as in the input',
  tied[0].name === 'Pad 10' && tied[1].name === 'Pad 9',
  tied.map((r) => r.name).join(' '))

// --- against the real catalog --------------------------------------------

const here = dirname(fileURLToPath(import.meta.url))
const csv = join(here, '..', '..', 'storm_products_tagged.csv')

if (existsSync(csv)) {
  console.log('\n== the real catalog ==')
  const lines = readFileSync(csv, 'utf8').split('\n').filter(Boolean)
  const header = lines[0].split(',')
  const nameAt = header.indexOf('name')
  const skuAt = header.indexOf('sku')

  // Good enough for names without embedded commas; rows that do not parse are
  // skipped rather than allowed to distort the check.
  const real: Product[] = lines.slice(1)
    .map((line) => line.split(','))
    .filter((cells) => cells.length === header.length)
    .map((cells, i) => product({
      name: cells[nameAt] ?? '',
      sku: cells[skuAt] ?? '',
      price: (i % 11) * 9.5,
    }))

  check('parsed a realistic number of products', real.length > 200, String(real.length))

  const realByName = sortProducts(real, 'name')
  const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true })
  check('every adjacent pair is in order',
    realByName.every((row, i) => i === 0 || collator.compare(realByName[i - 1].name, row.name) <= 0))
  check('nothing was lost or duplicated', realByName.length === real.length)

  const realByPrice = sortProducts(real, 'price')
  const firstZero = realByPrice.findIndex((r) => r.price <= 0)
  check('no priced product appears after a zero-price one',
    firstZero === -1 || realByPrice.slice(firstZero).every((r) => r.price <= 0),
    `first zero at ${firstZero} of ${realByPrice.length}`)
  console.log(`        (${real.length} products, cheapest "${realByPrice[0].name.slice(0, 34)}")`)
} else {
  console.log('\n(skipping the real-catalog checks: storm_products_tagged.csv not found)')
}

console.log(`\n${passed}/${passed + failed} passed`)
process.exit(failed === 0 ? 0 : 1)
