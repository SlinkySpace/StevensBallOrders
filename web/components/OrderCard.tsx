'use client'

/**
 * One order: heading, status pill, total, and its line items behind a toggle.
 *
 * Outstanding Orders, Order History and the Owner Dashboard all show the same
 * thing, so it lives here once. The owner's version adds the customer and a
 * status control, passed in as `extra` rather than branching in here.
 */

import { useState } from 'react'
import type { Order } from '@/lib/api'
import { currency, orderMeta, pillClass } from '@/lib/format'

export function OrderCard({ order, showCustomer = false, extra, defaultOpen = false }: {
  order: Order
  showCustomer?: boolean
  extra?: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const items = order.items ?? []

  const body = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '10px 14px' }}>
        <span style={{ font: '700 16px/1 Archivo, sans-serif', letterSpacing: '-0.01em' }}>
          Order #{order.id}
        </span>
        <span className={pillClass(order.status)}>{order.status}</span>
        {showCustomer && (
          <span style={{
            font: "600 13px/1.3 'Source Sans 3', sans-serif", color: 'var(--dim)',
          }}>
            {order.customer_first_name} {order.customer_last_name} · {order.customer_email}
          </span>
        )}
        <span className="num" style={{
          font: '700 17px/1 Archivo, sans-serif', marginLeft: 'auto',
        }}>{currency(order.total_price)}</span>
      </div>

      <div style={{ fontSize: 13, color: 'var(--dim)', marginTop: 6 }}>{orderMeta(order)}</div>

      {order.note && (
        <div style={{
          fontSize: 13, color: 'var(--dim)', marginTop: 6, fontStyle: 'italic',
        }}>Note: {order.note}</div>
      )}

      <button onClick={() => setOpen(!open)} style={{
        marginTop: 14, background: 'transparent', border: '1px solid var(--border)',
        borderRadius: 7, padding: '7px 12px', color: 'var(--dim)',
        font: "600 12px/1 'Source Sans 3', sans-serif", cursor: 'pointer', whiteSpace: 'nowrap',
      }}>
        {open ? 'Hide items' : `${items.length} line${items.length === 1 ? '' : 's'}`}
      </button>

      {open && (
        <div className="rows" style={{ marginTop: 14 }}>
          <div className="rows__head">
            <div>Product</div><div>SKU</div><div>Option</div>
            <div className="right">Qty</div><div className="right">Unit</div>
            <div className="right">Line total</div>
          </div>
          {items.map((item) => (
            <div className="rows__row" key={item.id}>
              <div title={item.product_name}>{item.product_name}</div>
              <div className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {item.sku || '—'}
              </div>
              <div style={{ color: 'var(--dim)' }}>{item.option_value || '—'}</div>
              <div className="right num">{item.quantity}</div>
              <div className="right num" style={{ color: 'var(--dim)' }}>
                {currency(item.unit_price)}
              </div>
              <div className="right num" style={{ fontWeight: 600 }}>
                {currency(item.total_price)}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )

  if (!extra) {
    return (
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 13, padding: '18px 20px',
      }}>{body}</div>
    )
  }

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 12,
      padding: '16px 18px', background: 'var(--bg)',
    }}>
      <div className="owner-order" style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 210px',
        gap: 20, alignItems: 'start',
      }}>
        <div style={{ minWidth: 0 }}>{body}</div>
        <div style={{ display: 'grid', gap: 8, alignContent: 'start' }}>{extra}</div>
      </div>
      <style>{`
        @media (max-width: 820px) {
          .owner-order { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  )
}

export function Stats({ figures }: { figures: [string, string][] }) {
  return (
    <div className="stats">
      {figures.map(([label, value], index) => (
        <div key={label}>
          <div className="stat-label">{label}</div>
          <div className={`stat-value${index === figures.length - 1 ? ' stat-value--accent' : ''}`}>
            {value}
          </div>
        </div>
      ))}
    </div>
  )
}

export function Empty({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div className="empty">
      <div className="empty__icon">{icon}</div>
      <div className="empty__title">{title}</div>
      <div className="empty__body">{body}</div>
    </div>
  )
}
