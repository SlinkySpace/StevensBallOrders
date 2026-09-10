'use client'

import { useEffect, useMemo, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { useApp } from '@/app/providers'
import { api, type Freshness, type Product } from '@/lib/api'
import { currency, defaultOption, imageSrc, productMeta } from '@/lib/format'

const PER_PAGE = 24

const QUICK = [
  { label: 'All', main: '', sub: '' },
  { label: 'Bowling Balls', main: '', sub: 'Bowling Balls' },
  { label: 'Bags', main: '', sub: 'Bowling Bags' },
  { label: 'Shoes', main: '', sub: 'Shoes' },
  { label: 'Apparel', main: '', sub: 'Apparel' },
]

export default function CatalogPage() {
  return <Chrome><Catalog /></Chrome>
}

function Catalog() {
  const { addToCart, notify } = useApp()
  const [products, setProducts] = useState<Product[]>([])
  const [mains, setMains] = useState<string[]>([])
  const [subs, setSubs] = useState<string[]>([])
  const [fresh, setFresh] = useState<Freshness | null>(null)
  const [loading, setLoading] = useState(true)

  const [search, setSearch] = useState('')
  const [main, setMain] = useState('')
  const [sub, setSub] = useState('')
  const [page, setPage] = useState(1)
  const [openFor, setOpenFor] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([api.products(), api.freshness().catch(() => null)])
      .then(([catalog, freshness]) => {
        if (cancelled) return
        setProducts(catalog.products)
        setMains(catalog.main_categories)
        setSubs(catalog.sub_categories)
        setFresh(freshness)
      })
      .catch((error: unknown) => {
        notify(error instanceof Error ? error.message : 'Could not load the catalog.', 'bad')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [notify])

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return products.filter((product) => {
      if (main && product.main_category !== main) return false
      if (sub && product.sub_category !== sub) return false
      if (!needle) return true
      return (
        product.name.toLowerCase().includes(needle) ||
        String(product.sku ?? '').toLowerCase().includes(needle)
      )
    })
  }, [products, search, main, sub])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE))
  const current = Math.min(page, totalPages)
  const start = (current - 1) * PER_PAGE
  const shown = filtered.slice(start, start + PER_PAGE)

  useEffect(() => { setPage(1) }, [search, main, sub])

  return (
    <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
      <div style={{
        position: 'relative', overflow: 'hidden', border: '1px solid var(--border)',
        borderRadius: 16, background: 'var(--bg2)', padding: '28px 32px', marginBottom: 28,
      }}>
        <div className="lanes" style={{ inset: '-120% -20% auto auto', width: 640, height: 640 }} />
        <div style={{
          position: 'relative', display: 'flex', alignItems: 'flex-end',
          justifyContent: 'space-between', gap: 24, flexWrap: 'wrap',
        }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 12 }}>Storm catalog</div>
            <h1 style={{
              font: '800 clamp(30px, 3.4vw, 44px)/1 Archivo, sans-serif',
              letterSpacing: '-0.03em', margin: '0 0 8px',
            }}>Catalog</h1>
            <p style={{ fontSize: 15, color: 'var(--dim)', margin: 0 }}>
              Storm equipment at team sponsor pricing.
              {fresh && (
                <span style={{ color: fresh.stale ? 'var(--ink)' : 'var(--dim2)' }}>
                  {' '}Prices updated {fresh.age}.
                </span>
              )}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {QUICK.map((quick) => {
              const active = main === quick.main && sub === quick.sub
              return (
                <button key={quick.label}
                  onClick={() => { setMain(quick.main); setSub(quick.sub) }}
                  style={{
                    padding: '8px 14px', borderRadius: 999, cursor: 'pointer',
                    border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
                    background: active ? 'var(--soft)' : 'var(--card)',
                    color: active ? 'var(--ink)' : 'var(--dim)',
                    font: `${active ? 700 : 600} 12px/1 'Source Sans 3', sans-serif`,
                  }}>{quick.label}</button>
              )
            })}
          </div>
        </div>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr)',
        gap: 12, marginBottom: 14,
      }}>
        <input className="field" value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="Search by product name or SKU" />
        <Select value={main} onChange={setMain} options={mains} allLabel="All categories" />
        <Select value={sub} onChange={setSub} options={subs} allLabel="All sub-categories" />
      </div>

      <div style={{ fontSize: 13, color: 'var(--dim2)', marginBottom: 20 }}>
        {loading ? 'Loading the catalog…'
          : `Showing ${filtered.length ? start + 1 : 0}–${Math.min(start + PER_PAGE, filtered.length)} of ${filtered.length} products${totalPages > 1 ? ` · page ${current} of ${totalPages}` : ''}`}
      </div>

      {!loading && filtered.length === 0 && (
        <div className="empty">
          <div className="empty__icon">🎳</div>
          <div className="empty__title">No products match those filters.</div>
          <div className="empty__body">Try a different category or clear the search.</div>
        </div>
      )}

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 18,
      }}>
        {shown.map((product) => (
          <ProductCard
            key={product.product_url}
            product={product}
            open={openFor === product.product_url}
            onToggle={() => setOpenFor(openFor === product.product_url ? null : product.product_url)}
            onAdd={(line) => {
              addToCart(line)
              setOpenFor(null)
              notify(`${line.quantity} × ${line.name} added to your cart.`)
            }}
          />
        ))}
      </div>

      {totalPages > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, marginTop: 32, paddingTop: 24, borderTop: '1px solid var(--border)',
        }}>
          <button className="btn-quiet" disabled={current <= 1}
                  onClick={() => setPage(current - 1)}>← Previous</button>
          <div style={{ fontSize: 13, color: 'var(--dim)' }}>Page {current} of {totalPages}</div>
          <button className="btn-quiet" disabled={current >= totalPages}
                  onClick={() => setPage(current + 1)}>Next →</button>
        </div>
      )}
    </main>
  )
}

function Select({ value, onChange, options, allLabel }: {
  value: string; onChange: (next: string) => void; options: string[]; allLabel: string
}) {
  return (
    <div style={{ position: 'relative' }}>
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}
              style={{ paddingRight: 32, cursor: 'pointer', background: 'var(--card)' }}>
        <option value="">{allLabel}</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      <span style={{
        position: 'absolute', right: 13, top: '50%', transform: 'translateY(-50%)',
        pointerEvents: 'none', color: 'var(--dim2)', fontSize: 10,
      }}>▼</span>
    </div>
  )
}

function ProductCard({ product, open, onToggle, onAdd }: {
  product: Product
  open: boolean
  onToggle: () => void
  onAdd: (line: import('@/lib/api').CartLine) => void
}) {
  const [option, setOption] = useState(() => defaultOption(product))
  const [qty, setQty] = useState(1)
  const [note, setNote] = useState('')
  const src = imageSrc(product.image_url)
  const isBall = product.product_type === 'bowling_ball'
  const href = `/product?ref=${encodeURIComponent(product.product_url)}`

  return (
    <div style={{
      position: 'relative', background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: 14, display: 'flex', flexDirection: 'column',
    }}>
      <a href={href} style={{ position: 'relative', display: 'block' }}>
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={product.name} loading="lazy" decoding="async" style={{
            width: '100%', aspectRatio: '1 / 1', objectFit: 'contain', borderRadius: 10,
            padding: 6, background: 'rgba(128,128,128,0.05)',
            border: '1px solid rgba(128,128,128,0.12)',
          }} />
        ) : (
          <div style={{
            width: '100%', aspectRatio: '1 / 1', borderRadius: 10,
            background: 'rgba(128,128,128,0.05)', border: '1px solid rgba(128,128,128,0.12)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--dim2)', fontSize: 13,
          }}>No image</div>
        )}
        {isBall && (
          <div style={{
            position: 'absolute', left: 8, top: 8, padding: '4px 8px', borderRadius: 999,
            background: 'var(--bg)', border: '1px solid var(--border)',
            font: "600 9px/1 'Source Sans 3', sans-serif", letterSpacing: '0.1em',
            textTransform: 'uppercase', color: 'var(--dim)',
          }}>Ball</div>
        )}
      </a>

      <a href={href} title={product.name} style={{
        font: "600 15px/1.3 'Source Sans 3', sans-serif", letterSpacing: '-0.005em',
        margin: '12px 0 8px', height: '2.6em', overflow: 'hidden',
        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        color: 'var(--text)', textDecoration: 'none',
      }}>{product.name}</a>

      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 8, marginBottom: 12,
      }}>
        <span className="num" style={{
          font: '700 21px/1 Archivo, sans-serif', letterSpacing: '-0.02em',
        }}>{currency(product.price)}</span>
        <span title={product.sku} className="mono" style={{
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '45%',
        }}>{product.sku || '—'}</span>
      </div>

      <button onClick={onToggle} style={{
        marginTop: 'auto', width: '100%', padding: 10, borderRadius: 8,
        border: '1px solid rgba(163,38,56,0.28)', background: 'var(--soft)',
        color: 'var(--ink)', font: "700 13px/1 'Source Sans 3', sans-serif", cursor: 'pointer',
      }}>Add to cart</button>

      {open && (
        <div style={{
          position: 'absolute', left: 8, right: 8, bottom: 8, zIndex: 20,
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12,
          boxShadow: '0 18px 44px rgba(0,0,0,0.22)', padding: 14,
          animation: 'rollin 0.14s ease-out',
        }}>
          <div style={{ font: "600 14px/1.3 'Source Sans 3', sans-serif", marginBottom: 3 }}>
            {product.name}
          </div>
          <div style={{ fontSize: 12, color: 'var(--dim)', marginBottom: 12 }}>
            {productMeta(product)}
          </div>

          {product.options?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <label className="label label--sm">{product.option_type}</label>
              <select className="field field--sm" value={option}
                      onChange={(e) => setOption(e.target.value)} style={{ cursor: 'pointer' }}>
                {product.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 8, marginBottom: 10 }}>
            <div>
              <label className="label label--sm">Qty</label>
              <input className="field field--sm" type="number" min={1} max={20} value={qty}
                     onChange={(e) => setQty(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
            </div>
            <div>
              <label className="label label--sm">Note</label>
              <input className="field field--sm" value={note} placeholder="optional"
                     onChange={(e) => setNote(e.target.value)} />
            </div>
          </div>

          <a href={product.product_url} target="_blank" rel="noreferrer"
             style={{ display: 'block', fontSize: 12, marginBottom: 12 }}>
            View on stormbowling.com ↗
          </a>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => onAdd({
              product_url: product.product_url, name: product.name, sku: product.sku,
              unit_price: Number(product.price), quantity: qty,
              option_type: product.option_type, option_value: option,
              note, image_url: product.image_url, product_type: product.product_type,
              scent: product.scent,
            })} style={{
              flex: 1, padding: 10, border: 0, borderRadius: 8, background: 'var(--primary)',
              color: '#fff', font: "700 13px/1 'Source Sans 3', sans-serif", cursor: 'pointer',
            }}>Add to cart</button>
            <button onClick={onToggle} style={{
              padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8,
              background: 'transparent', color: 'var(--dim)',
              font: "600 13px/1 'Source Sans 3', sans-serif", cursor: 'pointer',
            }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
