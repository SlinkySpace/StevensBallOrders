/**
 * The orders CSV export.
 *
 *   node --experimental-strip-types web/lib/orders-csv.test.ts
 *
 * The shape is checked against the hand-kept sheet it replaces, Lillie's ten
 * lines and 365.38 subtotal included, so "matches the sheet" is an assertion
 * rather than a claim.
 */

import { ORDER_CSV_HEADER, ordersToCsv } from './orders-csv.ts'
import type { Order, OrderItem } from './api.ts'

let passed = 0
let failed = 0

function check(label: string, ok: boolean, extra = '') {
  if (ok) { passed++; console.log(`PASS  ${label}`) }
  else { failed++; console.log(`FAIL  ${label}${extra ? `\n        ${extra}` : ''}`) }
}

let nextId = 1
function item(over: Partial<OrderItem>): OrderItem {
  return {
    id: nextId++, product_name: '', sku: '', option_type: '', option_value: '',
    quantity: 1, unit_price: 0, total_price: 0, note: '', product_url: '',
    ...over,
  }
}

function order(first: string, email: string, items: OrderItem[], over: Partial<Order> = {}): Order {
  return {
    id: nextId++, customer_first_name: first, customer_last_name: 'Tester',
    customer_email: email, note: '', total_price: 0, status: 'submitted',
    timestamp: '2026-09-20T10:00:00', item_count: items.length, items,
    ...over,
  }
}

/** A line as the sheet holds it: price is the line total, not the unit price. */
const line = (name: string, notes: string, qty: number, each: number, url = 'https://x/y') =>
  item({
    product_name: name, option_value: notes, quantity: qty,
    unit_price: each, total_price: Number((qty * each).toFixed(2)), product_url: url,
  })

const cells = (row: string) => row.split(',')

/** Rows without the trailing newline, so indexes line up with the sheet. */
const lines = (csv: string) => csv.replace(/\n$/, '').split('\n')

const HEADER = ORDER_CSV_HEADER.join(',')

console.log('== the header matches the sheet ==')
check('seven columns, named as the sheet names them',
  HEADER === 'Name,Item,Notes,Quantity,Link,Price,Total', HEADER)
check('an empty export is the header alone', ordersToCsv([]) === `${HEADER}\n`,
  JSON.stringify(ordersToCsv([])))

console.log('\n== Lillie, straight off the sheet ==')
const lillie = ordersToCsv([order('Lillie', 'lillie@stevens.edu', [
  line('STORM PTLP GRIP BAG', '', 1, 7),
  line('Abralon pad 500 Grit', '', 1, 2.89),
  line('Equinox Hybrid', '15 pound', 1, 120),
  line('Abralon pad 1000 Grit', '', 2, 2.89),
  line('Gremlin Tour X', '15 pounds', 1, 105),
  line('Typhoon', '15 pounds', 1, 95),
  line('Power Edge', '', 1, 9.9),
  line('Reacta Foam', '', 2, 5.78),
  line('Super Bond Adhesive', '', 1, 7),
  line('PRO SHOP PENCIL', '', 1, 1.25),
])])
const lillieRows = lines(lillie)

check('header, ten items, one subtotal', lillieRows.length === 12, String(lillieRows.length))
check('the name repeats down every item row',
  lillieRows.slice(1, 11).every((r) => cells(r)[0] === 'Lillie Tester'))
check('two pads at 2.89 price as 5.78, not 2.89',
  cells(lillieRows[4])[5] === '5.78', lillieRows[4])
check('a whole price has no trailing zeros, as in the sheet',
  cells(lillieRows[3])[5] === '120', lillieRows[3])
check('9.9 stays 9.9', cells(lillieRows[7])[5] === '9.9', lillieRows[7])
check('the Total column is empty on item rows',
  lillieRows.slice(1, 11).every((r) => cells(r)[6] === ''))
check('the subtotal is 365.38, the figure on the sheet',
  cells(lillieRows[11])[6] === '365.38', lillieRows[11])
check('the subtotal row carries the name and nothing between',
  cells(lillieRows[11]).join('|') === 'Lillie Tester||||||365.38', lillieRows[11])
check('the weight lands in Notes', cells(lillieRows[3])[2] === '15 pound', lillieRows[3])

console.log('\n== people are separated, and each closes with its own subtotal ==')
const many = ordersToCsv([
  order('Hayden', 'hayden@stevens.edu', [line('Bionic', '14 lbs', 1, 110)]),
  order('Josh', 'josh@stevens.edu', [
    line('Ion Max', '15 lbs', 1, 120), line('Bionic', '15 lbs', 1, 110),
  ]),
  order('CJ', 'cj@stevens.edu', [
    line('Gremlin Tour-X', '15 lbs', 1, 105), line('Equinox Hybrid', '15 lbs', 1, 120),
  ]),
])
const manyRows = lines(many)
const blanks = manyRows.filter((r) => r === ',,,,,,')

check('a blank row sits between people', blanks.length === 2, String(blanks.length))
check('and not after the last one', manyRows[manyRows.length - 1] !== ',,,,,,',
  JSON.stringify(manyRows[manyRows.length - 1]))
check('every row has seven fields, blanks included',
  manyRows.every((r) => cells(r).length === 7),
  manyRows.map((r) => cells(r).length).join(' '))
check("Josh's subtotal is 230", many.includes('Josh Tester,,,,,,230'), many)
check("CJ's subtotal is 225", many.includes('CJ Tester,,,,,,225'), many)
check('people keep the order they arrived in, not alphabetical',
  manyRows.findIndex((r) => r.startsWith('Hayden')) <
    manyRows.findIndex((r) => r.startsWith('Josh')) &&
  manyRows.findIndex((r) => r.startsWith('Josh')) <
    manyRows.findIndex((r) => r.startsWith('CJ')))

console.log('\n== grouping is per person, not per order ==')
const split = ordersToCsv([
  order('Andrew', 'andrew@stevens.edu', [line('Concept', '15 lbs', 1, 120)]),
  order('Kaiyiu', 'kaiyiu@stevens.edu', [line('Bionic', '13 lbs', 1, 110)]),
  order('Andrew', 'andrew@stevens.edu', [line('Next Factor', '15 lbs', 1, 120)]),
])
check('two orders from one person make one block',
  lines(split).filter((r) => r.startsWith('Andrew')).length === 3, split)
check('and one subtotal covering both, 240',
  split.includes('Andrew Tester,,,,,,240'), split)
check('the other person is untouched', split.includes('Kaiyiu Tester,,,,,,110'), split)

// Email is the identity: a display-name change must not split someone in two.
const renamed = ordersToCsv([
  order('Kate', 'k@stevens.edu', [line('Ball', '15 lbs', 1, 100)]),
  order('Katherine', 'k@stevens.edu', [line('Bag', '', 1, 50)]),
])
check('a renamed person stays one block',
  lines(renamed).filter((r) => r === ',,,,,,').length === 0, renamed)
check('and is named as they are now', renamed.includes('Katherine Tester,,,,,,150'), renamed)

console.log('\n== awkward values ==')
const nasty = ordersToCsv([order('Ann', 'ann@stevens.edu', [
  item({
    product_name: 'Ball, "Pro" model', option_value: '15 lbs', note: 'drill it lefty',
    quantity: 1, unit_price: 10, total_price: 10, product_url: 'https://x/a?b=1&c=2',
  }),
])])
check('a comma and quotes in a name are escaped',
  nasty.includes('"Ball, ""Pro"" model"'), nasty)
check('the weight and the note share the Notes cell',
  nasty.includes('15 lbs - drill it lefty'), nasty)
check('a URL with a query survives', nasty.includes('https://x/a?b=1&c=2'), nasty)
check('the row still has seven fields',
  cells(lines(nasty)[1].replace(/"[^"]*"/g, 'X')).length === 7, nasty)

console.log('\n== nothing to export ==')
check('an order with no items produces no block',
  ordersToCsv([order('Empty', 'empty@stevens.edu', [])]) === `${HEADER}\n`)
const single = ordersToCsv([
  order('N', 'n@stevens.edu', [item({ product_name: 'X', total_price: 5 })]),
])
check('a missing product_url leaves Link empty',
  lines(single)[1] === 'N Tester,X,,1,,5,', single)

console.log('\n== the subtotal adds up over many awkward lines ==')
// Summed as floats, ten lots of 9.99 land on 99.89999999999999.
const driftItems = Array.from({ length: 10 }, () => line('Cloth', '', 3, 3.33))
const drift = ordersToCsv([order('Drift', 'd@stevens.edu', driftItems)])
check('ten lines of 3 x 3.33 total 99.9, with no float dust',
  drift.includes('Drift Tester,,,,,,99.9'), lines(drift).slice(-1)[0])

console.log('\n== the file ends as a text file should ==')
check('there is a trailing newline, and only one',
  many.endsWith('\n') && !many.endsWith('\n\n'), JSON.stringify(many.slice(-14)))

console.log(`\n${passed}/${passed + failed} passed`)
process.exit(failed === 0 ? 0 : 1)
