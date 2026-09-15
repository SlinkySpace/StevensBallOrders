// Written with the extension so that `node --experimental-strip-types` can
// resolve it: the tests run straight off these files, with no build step, and
// bare Node ESM does not guess at extensions the way the bundler does.
import { SORTS, type Sort } from './sort.ts'

/**
 * Where a shopper had got to in the catalog, carried in the URL.
 *
 * Opening a product is a navigation, so the catalog unmounts and every useState
 * in it goes with it. Keeping the browse state in the query string instead means
 * coming back restores the search, the filters, the sort and the page - and it
 * survives a refresh, a shared link and the browser's own back button, none of
 * which a module-level variable would.
 *
 * Only these five keys are ever read or written, so a hand-edited URL cannot
 * put anything else into the page's state.
 */
export type Browse = {
  search: string
  main: string
  sub: string
  sort: Sort
  page: number
}

export const EMPTY_BROWSE: Browse = {
  search: '',
  main: '',
  sub: '',
  sort: 'default',
  page: 1,
}

/** Enough of URLSearchParams to read; Next's ReadonlyURLSearchParams fits too. */
type Readable = { get(key: string): string | null }

export function readBrowse(params: Readable): Browse {
  const sort = params.get('sort') ?? ''
  const page = Number.parseInt(params.get('page') ?? '', 10)

  return {
    search: params.get('q') ?? '',
    main: params.get('main') ?? '',
    sub: params.get('sub') ?? '',
    // An unknown sort falls back rather than leaving the <select> bound to a
    // value it has no <option> for, which renders as blank.
    sort: SORTS.some((option) => option.value === sort) ? (sort as Sort) : 'default',
    page: Number.isFinite(page) && page > 1 ? page : 1,
  }
}

/**
 * The query string for a browse state, without the leading "?".
 *
 * Defaults are left out, so an untouched catalog stays at "/" rather than
 * "/?q=&main=&sub=&sort=default&page=1".
 */
export function browseQuery(state: Browse): string {
  const params = new URLSearchParams()
  if (state.search.trim()) params.set('q', state.search)
  if (state.main) params.set('main', state.main)
  if (state.sub) params.set('sub', state.sub)
  if (state.sort !== 'default') params.set('sort', state.sort)
  if (state.page > 1) params.set('page', String(state.page))
  return params.toString()
}

/**
 * A link back to the catalog, from a "back" parameter the catalog put on the
 * product link.
 *
 * The value is round-tripped through readBrowse rather than pasted onto "/?",
 * so only the five known keys survive and the sort is validated - a link
 * arriving with anything else in it lands on a clean catalog.
 */
export function backToCatalog(back: string | null | undefined): string {
  const query = browseQuery(readBrowse(new URLSearchParams(back ?? '')))
  return query ? `/?${query}` : '/'
}

/** The product link for a card, carrying the catalog state to come back to. */
export function productHref(productUrl: string, back: string): string {
  const query = `ref=${encodeURIComponent(productUrl)}`
  return back ? `/product?${query}&back=${encodeURIComponent(back)}` : `/product?${query}`
}
