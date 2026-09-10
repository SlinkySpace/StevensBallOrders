'use client'

import { useEffect, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { useApp } from '@/app/providers'
import { api, type Product } from '@/lib/api'
import { cartTotal, cartUnits, currency, imageSrc, lineTotal, productMeta } from '@/lib/format'

export default function CartPage() {
  return <Chrome><Cart /></Chrome>
}

function Cart() {
  const { cart, updateLine, removeLine, emptyCart, notify } = useApp()
  // Only for the option dropdowns: a saved cart line remembers which option was
  // chosen but not the list it came from.
  const [options, setOptions] = useState<Record<string, string[]>>({})

  useEffect(() => {
    api.products()
      .then(({ products }) => {
        const map: Record<string, string[]> = {}
        products.forEach((product: Product) => {
          if (product.options?.length) map[product.product_url] = product.options
        })
        setOptions(map)
      })
      .catch(() => { /* the dropdown just falls back to the saved value */ })
  }, [])

  if (cart.length === 0) {
    return (
      <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
        <h1 className="h1">Cart</h1>
        <p className="sub">Set quantities and weights here, then head to checkout.</p>
        <div className="empty">
          <div className="empty__icon">🛒</div>
          <div className="empty__title">Your cart is empty</div>
          <div className="empty__body" style={{ marginBottom: 22 }}>
            Add something from the catalog and it turns up here.
          </div>
          <a href="/" className="btn" style={{ display: 'inline-block', textDecoration: 'none' }}>
            Browse the catalog
          </a>
        </div>
      </main>
    )
  }

  const total = cartTotal(cart)
  const units = cartUnits(cart)

  return (
    <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
      <h1 className="h1">Cart</h1>
      <p className="sub">Set quantities and weights here, then head to checkout.</p>

      <div className="cart-grid" style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 340px',
        gap: 28, alignItems: 'start',
      }}>
        <div style={{ display: 'grid', gap: 14 }}>
          {cart.map((line, index) => {
            const src = imageSrc(line.image_url)
            const choices = options[line.product_url] ?? (line.option_value ? [line.option_value] : [])
            return (
              <div key={`${line.product_url}-${line.option_value}-${index}`} className="card" style={{
                padding: 18, display: 'grid',
                gridTemplateColumns: src ? '104px minmax(0, 1fr)' : 'minmax(0, 1fr)', gap: 18,
              }}>
                {src && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={src} alt={line.name} style={{
                    width: 104, height: 104, objectFit: 'contain', borderRadius: 10,
                    background: 'rgba(128,128,128,0.05)',
                    border: '1px solid rgba(128,128,128,0.12)', padding: 6,
                  }} />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{
                    font: "600 17px/1.25 'Source Sans 3', sans-serif",
                    letterSpacing: '-0.01em', marginBottom: 5,
                  }}>{line.name}</div>
                  <div style={{ fontSize: 13, color: 'var(--dim)', marginBottom: 14 }}>
                    {productMeta(line)}
                  </div>

                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div style={{ width: 88 }}>
                      <label className="label label--sm">Qty</label>
                      <input className="field field--sm" type="number" min={1} max={20}
                             value={line.quantity}
                             onChange={(e) => updateLine(index, {
                               quantity: Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                             })} />
                    </div>

                    {choices.length > 0 && (
                      <div style={{ width: 120 }}>
                        <label className="label label--sm">{line.option_type || 'Option'}</label>
                        <select className="field field--sm" value={line.option_value}
                                onChange={(e) => updateLine(index, { option_value: e.target.value })}
                                style={{ cursor: 'pointer' }}>
                          {choices.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                    )}

                    <div style={{ flex: 1, minWidth: 150 }}>
                      <label className="label label--sm">Item note</label>
                      <input className="field field--sm" value={line.note}
                             onChange={(e) => updateLine(index, { note: e.target.value })} />
                    </div>

                    <button onClick={() => { removeLine(index); notify(`${line.name} removed.`) }}
                            className="btn-quiet" style={{
                              padding: '9px 12px', borderRadius: 7, fontSize: 13,
                              whiteSpace: 'nowrap', alignSelf: 'flex-end',
                            }}>Remove item</button>
                  </div>

                  <div style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                    marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)',
                    fontSize: 13, color: 'var(--dim)',
                  }}>
                    <span>Line total</span>
                    <span className="num" style={{
                      font: '700 18px/1 Archivo, sans-serif', color: 'var(--text)',
                    }}>{currency(lineTotal(line))}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <div className="card" style={{ position: 'sticky', top: 130, padding: 22 }}>
          <div style={{
            font: "700 12px/1 'Source Sans 3', sans-serif", letterSpacing: '0.1em',
            textTransform: 'uppercase', color: 'var(--dim)', marginBottom: 18,
          }}>Summary</div>

          <Row label="Items" value={String(units)} />
          <Row label="Lines" value={String(cart.length)} />

          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            paddingTop: 16, borderTop: '1px solid var(--border)', marginBottom: 20,
          }}>
            <span style={{
              font: "600 12px/1 'Source Sans 3', sans-serif", letterSpacing: '0.08em',
              textTransform: 'uppercase', color: 'var(--dim)',
            }}>Cart total</span>
            <span className="num" style={{
              font: '800 26px/1 Archivo, sans-serif', color: 'var(--ink)',
            }}>{currency(total)}</span>
          </div>

          <a href="/checkout" className="btn" style={{
            display: 'block', width: '100%', textAlign: 'center',
            textDecoration: 'none', marginBottom: 10, padding: 13,
          }}>Checkout →</a>
          <button onClick={() => { emptyCart(); notify('Cart emptied.') }}
                  className="btn-quiet" style={{ width: '100%', padding: 11 }}>Empty cart</button>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .cart-grid { grid-template-columns: 1fr !important; }
          .cart-grid > div:last-child { position: static !important; }
        }
      `}</style>
    </main>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', fontSize: 14,
      color: 'var(--dim)', marginBottom: 10,
    }}>
      <span>{label}</span>
      <span className="num" style={{ color: 'var(--text)', fontWeight: 600 }}>{value}</span>
    </div>
  )
}
