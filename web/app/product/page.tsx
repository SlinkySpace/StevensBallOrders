'use client'

/**
 * One product, in full.
 *
 * Addressed by ?ref=<product_url> rather than /product/<sku>, because a SKU is
 * not a key here: sku_from_product_url only recovers one from Storm's older
 * /products/<main>/<sub>/<slug> URLs, so every root-level product has an empty
 * one. product_url is what the products table is keyed on.
 */

import { Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Chrome } from '@/components/Chrome'
import { useApp } from '@/app/providers'
import { api, type Product } from '@/lib/api'
import { currency, defaultOption, imageSrc } from '@/lib/format'

export default function ProductPage() {
  return (
    <Chrome>
      <Suspense fallback={<Loading />}>
        <Detail />
      </Suspense>
    </Chrome>
  )
}

function Loading() {
  return (
    <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
      <div style={{ fontSize: 13, color: 'var(--dim2)' }}>Loading…</div>
    </main>
  )
}

function Detail() {
  const params = useSearchParams()
  const ref = params.get('ref') || ''
  const { addToCart, notify } = useApp()

  const [products, setProducts] = useState<Product[] | null>(null)
  const [qty, setQty] = useState(1)
  const [note, setNote] = useState('')
  const [option, setOption] = useState('')

  useEffect(() => {
    let cancelled = false
    api.products()
      .then((catalog) => { if (!cancelled) setProducts(catalog.products) })
      .catch((error: unknown) => {
        if (cancelled) return
        setProducts([])
        notify(error instanceof Error ? error.message : 'Could not load the product.', 'bad')
      })
    return () => { cancelled = true }
  }, [notify])

  const product = useMemo(
    () => (products ?? []).find((p) => p.product_url === ref) ?? null,
    [products, ref],
  )

  // Set once the product arrives; a bowling ball defaults to 15 lb.
  useEffect(() => { if (product) setOption(defaultOption(product)) }, [product])

  if (products === null) return <Loading />

  if (!product) {
    return (
      <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
        <a href="/" className="btn-quiet" style={{ display: 'inline-block', marginBottom: 24 }}>
          ← Back to catalog
        </a>
        <div className="empty">
          <div className="empty__icon">🎳</div>
          <div className="empty__title">That product is not in the catalog.</div>
          <div className="empty__body">
            It may have been hidden or removed since the link was made.
          </div>
        </div>
      </main>
    )
  }

  const src = imageSrc(product.image_url)
  const scent = String(product.scent ?? '').trim()

  return (
    <main style={{ maxWidth: 1320, margin: '0 auto', padding: '28px 28px 80px' }}>
      <a href="/" className="btn-quiet" style={{ display: 'inline-block', marginBottom: 20 }}>
        ← Back to catalog
      </a>

      <div className="detail" style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)',
        gap: 48, alignItems: 'start',
      }}>
        <div style={{
          position: 'relative', overflow: 'hidden', background: 'var(--bg2)',
          border: '1px solid var(--border)', borderRadius: 18, padding: 40,
        }}>
          <div className="lanes" style={{ inset: 'auto auto -45% -25%', width: 520, height: 520 }} />
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={src} alt={product.name} style={{
              position: 'relative', width: '100%', aspectRatio: '1 / 1', objectFit: 'contain',
            }} />
          ) : (
            <div style={{
              position: 'relative', width: '100%', aspectRatio: '1 / 1', display: 'flex',
              alignItems: 'center', justifyContent: 'center', color: 'var(--dim2)', fontSize: 13,
            }}>No image</div>
          )}
        </div>

        <div>
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            {product.main_category} · {product.sub_category}
          </div>
          <h1 style={{
            font: '800 clamp(28px, 3vw, 40px)/1.05 Archivo, sans-serif',
            letterSpacing: '-0.03em', margin: '0 0 16px',
          }}>{product.name}</h1>

          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 24 }}>
            <div className="num" style={{
              font: '800 34px/1 Archivo, sans-serif', letterSpacing: '-0.02em',
            }}>{currency(product.price)}</div>
            {product.sku && <div className="mono">SKU {product.sku}</div>}
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 28 }}>
            <span className={product.in_stock ? 'pill pill--fulfilled' : 'pill pill--cancelled'}>
              {product.in_stock ? 'In stock' : 'Out of stock'}
            </span>
            {scent && scent.toLowerCase() !== 'none' && (
              <span style={{
                padding: '7px 12px', borderRadius: 999, background: 'var(--bg2)',
                border: '1px solid var(--border)', font: "600 11px/1 'Source Sans 3', sans-serif",
                color: 'var(--dim)', whiteSpace: 'nowrap',
              }}>Scent · {scent}</span>
            )}
          </div>

          <div className="card" style={{ padding: 20 }}>
            {product.options?.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <label className="label">{product.option_type}</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {product.options.map((choice) => {
                    const active = option === choice
                    return (
                      <button key={choice} onClick={() => setOption(choice)} style={{
                        padding: '10px 16px', borderRadius: 8, cursor: 'pointer',
                        whiteSpace: 'nowrap',
                        font: "600 14px/1 'Source Sans 3', sans-serif",
                        background: active ? 'var(--text)' : 'var(--bg)',
                        color: active ? 'var(--bg)' : 'var(--text)',
                        border: `1px solid ${active ? 'var(--text)' : 'var(--border)'}`,
                      }}>{choice}</button>
                    )
                  })}
                </div>
              </div>
            )}

            <div style={{
              display: 'grid', gridTemplateColumns: '120px minmax(0, 1fr)',
              gap: 12, marginBottom: 16,
            }}>
              <div>
                <label className="label">Quantity</label>
                <input className="field" type="number" min={1} max={20} value={qty}
                       onChange={(e) => setQty(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
              </div>
              <div>
                <label className="label">Note (optional)</label>
                <input className="field" value={note} placeholder="drilling, colour, anything"
                       onChange={(e) => setNote(e.target.value)} />
              </div>
            </div>

            <button className="btn" disabled={!product.in_stock} style={{ width: '100%', padding: 14 }}
                    onClick={() => {
                      addToCart({
                        product_url: product.product_url, name: product.name, sku: product.sku,
                        unit_price: Number(product.price), quantity: qty,
                        option_type: product.option_type, option_value: option,
                        note, image_url: product.image_url, product_type: product.product_type,
                        scent: product.scent,
                      })
                      notify(`${qty} × ${product.name} added to your cart.`)
                    }}>
              {product.in_stock
                ? `Add to cart · ${currency(Number(product.price) * qty)}`
                : 'Out of stock'}
            </button>
          </div>

          <a href={product.product_url} target="_blank" rel="noreferrer"
             style={{ display: 'inline-block', marginTop: 18, fontSize: 13 }}>
            View on stormbowling.com ↗
          </a>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .detail { grid-template-columns: 1fr !important; gap: 28px !important; }
        }
      `}</style>
    </main>
  )
}
