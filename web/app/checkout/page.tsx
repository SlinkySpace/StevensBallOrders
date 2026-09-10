'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Chrome } from '@/components/Chrome'
import { useApp } from '@/app/providers'
import { api, ApiError } from '@/lib/api'
import { cartTotal, cartUnits, currency, lineTotal } from '@/lib/format'

export default function CheckoutPage() {
  return <Chrome><Checkout /></Chrome>
}

function Checkout() {
  const { cart, clearCartLocal, refresh, notify } = useApp()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const router = useRouter()

  if (cart.length === 0) {
    return (
      <main style={{ maxWidth: 1000, margin: '0 auto', padding: '36px 28px 80px' }}>
        <h1 className="h1">Checkout</h1>
        <p className="sub">Everything below goes in as one order.</p>
        <div className="empty">
          <div className="empty__icon">✅</div>
          <div className="empty__title">Your cart is empty</div>
          <div className="empty__body">Add something from the catalog first.</div>
        </div>
      </main>
    )
  }

  async function placeOrder() {
    setBusy(true)
    try {
      // Only the note is sent. The server prices the order from the cart it
      // holds, so what is charged cannot be set by this page.
      const { order_id } = await api.placeOrder(note)
      clearCartLocal()
      await refresh()
      notify(`Order #${order_id} placed.`)
      router.push('/outstanding')
    } catch (error) {
      notify(error instanceof ApiError ? error.message : 'Could not place the order.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  const columns = 'minmax(0, 2.4fr) 1fr 1fr 56px 90px 100px'

  return (
    <main style={{ maxWidth: 1000, margin: '0 auto', padding: '36px 28px 80px' }}>
      <h1 className="h1">Checkout</h1>
      <p className="sub">Everything below goes in as one order.</p>

      <div className="card" style={{ overflow: 'hidden', marginBottom: 20 }}>
        <div style={{
          display: 'grid', gridTemplateColumns: columns, gap: 12, padding: '13px 20px',
          background: 'var(--bg2)', borderBottom: '1px solid var(--border)',
          font: "600 10px/1 'Source Sans 3', sans-serif", letterSpacing: '0.1em',
          textTransform: 'uppercase', color: 'var(--dim)',
        }}>
          <div>Product</div><div>SKU</div><div>Option</div>
          <div className="right">Qty</div><div className="right">Unit price</div>
          <div className="right">Line total</div>
        </div>
        {cart.map((line, index) => (
          <div key={index} style={{
            display: 'grid', gridTemplateColumns: columns, gap: 12, padding: '15px 20px',
            borderBottom: '1px solid var(--border)', fontSize: 14, alignItems: 'center',
          }}>
            <div style={{ fontWeight: 600, minWidth: 0 }}>{line.name}</div>
            <div className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {line.sku || '—'}
            </div>
            <div style={{ color: 'var(--dim)', fontSize: 13 }}>
              {line.option_value ? `${line.option_type}: ${line.option_value}` : '—'}
            </div>
            <div className="right num">{line.quantity}</div>
            <div className="right num" style={{ color: 'var(--dim)' }}>{currency(line.unit_price)}</div>
            <div className="right num" style={{ fontWeight: 700 }}>{currency(lineTotal(line))}</div>
          </div>
        ))}
      </div>

      <div className="stats" style={{ marginBottom: 22 }}>
        <div>
          <div className="stat-label">Lines</div>
          <div className="stat-value">{cart.length}</div>
        </div>
        <div>
          <div className="stat-label">Items</div>
          <div className="stat-value">{cartUnits(cart)}</div>
        </div>
        <div>
          <div className="stat-label">Estimated total</div>
          <div className="stat-value stat-value--accent">{currency(cartTotal(cart))}</div>
        </div>
      </div>

      <label className="label">Checkout note (optional)</label>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3}
                className="field" style={{ resize: 'vertical', marginBottom: 22, lineHeight: 1.5 }} />

      <button className="btn" onClick={placeOrder} disabled={busy} style={{ padding: '14px 26px' }}>
        {busy ? 'Placing…' : 'Confirm and place order'}
      </button>
    </main>
  )
}
