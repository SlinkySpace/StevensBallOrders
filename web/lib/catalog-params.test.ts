/**
 * Catalog browse state in the URL.
 *
 *   node --experimental-strip-types web/lib/catalog-params.test.ts
 *
 * The point of the module is that opening a product and coming back lands the
 * shopper where they were, so most of this is round trips: build a state, turn
 * it into a link, read it back, and check nothing was lost or invented.
 */

import {
  EMPTY_BROWSE, backToCatalog, browseQuery, productHref, readBrowse, type Browse,
} from './catalog-params.ts'

let passed = 0
let failed = 0

function check(label: string, ok: boolean, extra = '') {
  if (ok) { passed++; console.log(`PASS  ${label}`) }
  else { failed++; console.log(`FAIL  ${label}${extra ? `\n        ${extra}` : ''}`) }
}

const read = (query: string): Browse => readBrowse(new URLSearchParams(query))
const same = (a: Browse, b: Browse) => JSON.stringify(a) === JSON.stringify(b)

console.log('== an untouched catalog ==')
check('no query reads as the empty state', same(read(''), EMPTY_BROWSE), JSON.stringify(read('')))
check('and writes no query at all', browseQuery(EMPTY_BROWSE) === '', browseQuery(EMPTY_BROWSE))

console.log('\n== a full state survives the round trip ==')
const full: Browse = {
  search: 'storm', main: 'Equipment', sub: 'Bowling Balls', sort: 'price-desc', page: 3,
}
const encoded = browseQuery(full)
check('every field comes back', same(read(encoded), full), `${encoded} -> ${JSON.stringify(read(encoded))}`)
check('the query is readable', encoded === 'q=storm&main=Equipment&sub=Bowling+Balls&sort=price-desc&page=3', encoded)

console.log('\n== defaults are left out of the URL ==')
check('page 1 is implied', !browseQuery({ ...EMPTY_BROWSE, page: 1 }).includes('page'))
check('the default sort is implied', !browseQuery({ ...EMPTY_BROWSE, sort: 'default' }).includes('sort'))
check('a blank search is implied', browseQuery({ ...EMPTY_BROWSE, search: '   ' }) === '')
check('but page 2 is written', browseQuery({ ...EMPTY_BROWSE, page: 2 }) === 'page=2')

console.log('\n== awkward values ==')
check('a category with a space round-trips',
  read(browseQuery({ ...EMPTY_BROWSE, sub: 'Bowling Bags' })).sub === 'Bowling Bags')
check('a search with & and = round-trips',
  read(browseQuery({ ...EMPTY_BROWSE, search: 'a&b=c' })).search === 'a&b=c')
check('a search with a + round-trips (not eaten as a space)',
  read(browseQuery({ ...EMPTY_BROWSE, search: '6+ lb' })).search === '6+ lb')
check('an accented search round-trips',
  read(browseQuery({ ...EMPTY_BROWSE, search: 'Rincón' })).search === 'Rincón')

console.log('\n== a hand-edited URL cannot corrupt the page ==')
// The <select> is bound to this value, so an unknown one would render blank.
check('an unknown sort falls back to default', read('sort=cheapest').sort === 'default')
check('an empty sort falls back to default', read('sort=').sort === 'default')
check('a real sort is kept', read('sort=price-asc').sort === 'price-asc')
check('page=abc falls back to 1', read('page=abc').page === 1)
check('page=0 falls back to 1', read('page=0').page === 1)
check('page=-4 falls back to 1', read('page=-4').page === 1)
check('page=2.9 reads as 2', read('page=2.9').page === 2)
check('an absurd page is left to the component to clamp', read('page=99999').page === 99999)

console.log('\n== the back link ==')
check('no back parameter goes to a clean catalog', backToCatalog(null) === '/')
check('an empty one does too', backToCatalog('') === '/')
check('a real one is restored', backToCatalog('q=storm&page=2') === '/?q=storm&page=2',
  backToCatalog('q=storm&page=2'))

// Only the five known keys are re-emitted, so nothing else can ride along.
check('unknown keys are dropped', backToCatalog('q=storm&evil=1&redirect=http://x') === '/?q=storm',
  backToCatalog('q=storm&evil=1&redirect=http://x'))
check('junk alone lands on a clean catalog', backToCatalog('evil=1') === '/')
check('the result is always a relative path',
  [null, '', 'q=a', 'evil=1', '//example.com', 'q=//example.com'].every(
    (value) => backToCatalog(value).startsWith('/?') || backToCatalog(value) === '/'),
  [null, '', '//example.com'].map((v) => backToCatalog(v)).join(' '))

console.log('\n== the product link ==')
const url = 'https://www.stormbowling.com/storm-hat-cardinal-red'
check('no state gives a bare product link',
  productHref(url, '') === `/product?ref=${encodeURIComponent(url)}`, productHref(url, ''))
check('the product URL is encoded', productHref(url, '').includes('https%3A%2F%2F'), productHref(url, ''))
check('state rides along as one encoded parameter',
  productHref(url, 'q=storm&page=2').endsWith(`&back=${encodeURIComponent('q=storm&page=2')}`),
  productHref(url, 'q=storm&page=2'))

console.log('\n== catalog -> product -> back, the whole way round ==')
for (const state of [
  EMPTY_BROWSE,
  { ...EMPTY_BROWSE, search: 'storm' },
  { ...EMPTY_BROWSE, sort: 'price-desc' as const, page: 7 },
  full,
  { search: 'a&b', main: 'Merchandise', sub: 'Accessories', sort: 'sku' as const, page: 2 },
]) {
  const href = productHref(url, browseQuery(state))
  // What the product page sees when the browser hands it that link.
  const seen = new URL(href, 'http://localhost').searchParams
  const landed = `/?${browseQuery(state)}`.replace(/\?$/, '')
  check(`${browseQuery(state) || '(no filters)'} comes back intact`,
    backToCatalog(seen.get('back')) === (browseQuery(state) ? landed : '/')
      && seen.get('ref') === url,
    `${href}\n        -> ${backToCatalog(seen.get('back'))}`)
}

console.log(`\n${passed}/${passed + failed} passed`)
process.exit(failed === 0 ? 0 : 1)
