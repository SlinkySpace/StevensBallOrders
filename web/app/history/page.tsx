'use client'

import { useEffect, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { Empty, OrderCard, Stats } from '@/components/OrderCard'
import { useApp } from '@/app/providers'
import { api, type Order } from '@/lib/api'
import { currency, downloadCsv, ordersToCsv } from '@/lib/format'

export default function HistoryPage() {
  return <Chrome><History /></Chrome>
}

function History() {
  const { notify } = useApp()
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.orders()
      .then(({ orders: mine }) => setOrders(mine))
      .catch((error: unknown) =>
        notify(error instanceof Error ? error.message : 'Could not load orders.', 'bad'))
      .finally(() => setLoading(false))
  }, [notify])

  const items = orders.reduce((sum, order) => sum + (order.item_count ?? 0), 0)
  // Cancelled orders are not money the team spent, so they are left out of the
  // total even though the order itself stays in the list.
  const spent = orders
    .filter((order) => String(order.status).toLowerCase() !== 'cancelled')
    .reduce((sum, order) => sum + Number(order.total_price ?? 0), 0)

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 28px 80px' }}>
      <h1 className="h1">Order History</h1>
      <p className="sub">Every order you have placed, in any state.</p>

      {loading ? (
        <div style={{ color: 'var(--dim)', fontSize: 14 }}>Loading…</div>
      ) : orders.length === 0 ? (
        <Empty icon="🕘" title="No orders yet" body="Once you check out, your orders appear here." />
      ) : (
        <>
          <Stats figures={[
            ['Orders', String(orders.length)],
            ['Items', String(items)],
            ['Total ordered', currency(spent)],
          ]} />
          <div style={{ display: 'grid', gap: 12 }}>
            {orders.map((order) => <OrderCard key={order.id} order={order} />)}
          </div>
          <button className="btn-quiet" style={{ marginTop: 22, color: 'var(--text)' }}
                  onClick={() => downloadCsv('my_bowling_orders.csv', ordersToCsv(orders))}>
            Download my orders (CSV)
          </button>
        </>
      )}
    </main>
  )
}
