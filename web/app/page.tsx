import { getProducts, getCategories, getCatalogFreshness } from '@/lib/db'

export const dynamic = 'force-dynamic'

const PER_PAGE = 24

function currency(value: number) {
  return `$${Number(value ?? 0).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`
}

/**
 * The catalog images are committed into the Python app's static/ directory by
 * the refresh workflow. Stored as "static/catalog_images/x.webp", which the
 * Streamlit app serves at /app/static/...; here they are served from web/public
 * via a symlink or copy. Missing files fall back to the placeholder, same as
 * image_src() does.
 */
function imageSrc(stored: string): string | null {
  const value = String(stored ?? '').trim().split('\\').join('/')
  if (!value) return null
  if (/^(https?:|data:)/.test(value)) return value
  if (value.startsWith('static/')) return '/' + value
  return null
}

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; main?: string; sub?: string; page?: string }>
}) {
  const params = await searchParams
  const [all, categories, freshness] = await Promise.all([
    getProducts({ visibleOnly: true }),
    getCategories(),
    getCatalogFreshness(),
  ])

  const q = (params.q ?? '').trim().toLowerCase()
  const main = params.main ?? ''
  const sub = params.sub ?? ''

  const filtered = all.filter((p) => {
    if (main && p.main_category !== main) return false
    if (sub && p.sub_category !== sub) return false
    if (!q) return true
    return (
      String(p.name ?? '').toLowerCase().includes(q) ||
      String(p.sku ?? '').toLowerCase().includes(q)
    )
  })

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE))
  const page = Math.min(Math.max(1, Number.parseInt(params.page ?? '1', 10) || 1), totalPages)
  const start = (page - 1) * PER_PAGE
  const shown = filtered.slice(start, start + PER_PAGE)

  let synced = ''
  if (freshness?.value) {
    try {
      const record = JSON.parse(freshness.value) as { at?: string; mode?: string; count?: number }
      synced = [record.at?.replace('T', ' '), record.mode && `(${record.mode})`]
        .filter(Boolean).join(' ')
    } catch {
      synced = freshness.value
    }
  }

  const qs = (over: Record<string, string>) => {
    const sp = new URLSearchParams()
    if (q) sp.set('q', q)
    if (main) sp.set('main', main)
    if (sub) sp.set('sub', sub)
    for (const [k, v] of Object.entries(over)) v ? sp.set(k, v) : sp.delete(k)
    return '?' + sp.toString()
  }

  return (
    <>
      <div className="page-head">Catalog</div>
      <div className="page-sub">Storm equipment at team sponsor pricing.</div>

      <div className="banner">
        <strong>Read-only proof.</strong> This is the live database — {all.length} visible
        products{synced ? `, last synced ${synced}` : ''}. Nothing here can write;
        the Streamlit app is still the one you order from.
      </div>

      <form className="filters" method="get">
        <input type="search" name="q" defaultValue={q} placeholder="Search by product name or SKU" />
        <select name="main" defaultValue={main}>
          <option value="">All categories</option>
          {categories.main.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select name="sub" defaultValue={sub}>
          <option value="">All sub-categories</option>
          {categories.sub.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button type="submit" style={{ display: 'none' }}>Filter</button>
      </form>

      <div className="page-sub">
        Showing {filtered.length === 0 ? 0 : start + 1}–{Math.min(start + PER_PAGE, filtered.length)} of{' '}
        {filtered.length} products{totalPages > 1 ? ` · page ${page} of ${totalPages}` : ''}
      </div>

      <div className="grid">
        {shown.map((p) => {
          const src = imageSrc(p.image_url)
          return (
            <div className="card" key={p.product_url}>
              {src ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="product-image" src={src} alt={p.name} loading="lazy" decoding="async" />
              ) : (
                <div className="product-image product-image--empty">No image</div>
              )}
              <div className="product-name">{p.name}</div>
              <div className="product-line">
                <span className="product-price">{currency(p.price)}</span>
                <span className="product-sku">{p.sku || '—'}</span>
              </div>
            </div>
          )
        })}
      </div>

      {totalPages > 1 && (
        <div className="pager">
          {page > 1 ? <a href={qs({ page: String(page - 1) })}>← Previous</a> : <span>← Previous</span>}
          <span className="current">Page {page} of {totalPages}</span>
          {page < totalPages ? <a href={qs({ page: String(page + 1) })}>Next →</a> : <span>Next →</span>}
        </div>
      )}
    </>
  )
}
