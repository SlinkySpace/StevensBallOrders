import { getAllOrders } from '@/lib/db'

export const dynamic = 'force-dynamic'

const STATUS_CLASS: Record<string, string> = {
  submitted: 'status-submitted',
  approved: 'status-approved',
  ordered: 'status-ordered',
  fulfilled: 'status-fulfilled',
  cancelled: 'status-cancelled',
}

function currency(value: number) {
  return `$${Number(value ?? 0).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`
}

export default async function OrdersPage() {
  const orders = await getAllOrders()
  const items = orders.reduce((n, o) => n + o.item_count, 0)
  const value = orders
    .filter((o) => String(o.status).toLowerCase() !== 'cancelled')
    .reduce((n, o) => n + Number(o.total_price ?? 0), 0)

  return (
    <>
      <div className="page-head">Orders</div>
      <div className="page-sub">Every order in the database, newest first.</div>

      <div className="banner">
        <strong>Read-only proof.</strong> These are your real orders, rendered outside
        Streamlit. Statuses cannot be changed from here.
      </div>

      <div className="summary-row">
        <div>
          <div className="summary-label">Orders</div>
          <div className="summary-value">{orders.length}</div>
        </div>
        <div>
          <div className="summary-label">Items</div>
          <div className="summary-value">{items}</div>
        </div>
        <div>
          <div className="summary-label">Value</div>
          <div className="summary-value summary-value--accent">{currency(value)}</div>
        </div>
      </div>

      {orders.length === 0 && <p>No orders yet.</p>}

      {orders.map((order) => (
        <div className="order" key={order.id}>
          <div className="order-head">
            <span className="order-id">Order #{order.id}</span>
            <span className={`status-pill ${STATUS_CLASS[String(order.status).toLowerCase()] ?? 'status-submitted'}`}>
              {order.status}
            </span>
            <span className="order-meta">
              {order.customer_first_name} {order.customer_last_name} · {order.customer_email}
            </span>
            <span className="order-total">{currency(order.total_price)}</span>
          </div>
          <div className="order-meta">
            {order.timestamp} · {order.item_count} item{order.item_count === 1 ? '' : 's'}
          </div>
          {order.note && <div className="order-meta">Note: {order.note}</div>}

          <table className="items">
            <thead>
              <tr>
                <th>Product</th><th>SKU</th><th>Option</th>
                <th className="num">Qty</th><th className="num">Unit</th><th className="num">Line total</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.product_name}</td>
                  <td>{item.sku || '—'}</td>
                  <td>{item.option_value || '—'}</td>
                  <td className="num">{item.quantity}</td>
                  <td className="num">{currency(item.unit_price)}</td>
                  <td className="num">{currency(item.total_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  )
}
