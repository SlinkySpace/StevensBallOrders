'use client'

import { useEffect, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { Empty, OrderCard, Stats } from '@/components/OrderCard'
import { useApp } from '@/app/providers'
import { api, type Order } from '@/lib/api'
import { currency } from '@/lib/format'

// Matches config.ACTIVE_ORDER_STATUSES on the server.
const ACTIVE = ['submitted', 'approved', 'ordered']

export default function OutstandingPage() {
  return <Chrome><Outstanding /></Chrome>
}

function Outstanding() {
  const { notify } = useApp()
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.orders()
      .then(({ orders: mine }) =>
        setOrders(mine.filter((order) => ACTIVE.includes(String(order.status).toLowerCase()))))
      .catch((error: unknown) =>
        notify(error instanceof Error ? error.message : 'Could not load orders.', 'bad'))
      .finally(() => setLoading(false))
  }, [notify])

  const items = orders.reduce((sum, order) => sum + (order.item_count ?? 0), 0)
  const value = orders.reduce((sum, order) => sum + Number(order.total_price ?? 0), 0)

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 28px 80px' }}>
      <h1 className="h1">Outstanding Orders</h1>
      <p className="sub">Placed but not yet fulfilled.</p>

      {loading ? (
        <div style={{ color: 'var(--dim)', fontSize: 14 }}>Loading…</div>
      ) : orders.length === 0 ? (
        <Empty icon="📦" title="Nothing outstanding"
               body="Orders you place will show here until they are fulfilled." />
      ) : (
        <>
          <Stats figures={[
            ['Active orders', String(orders.length)],
            ['Items', String(items)],
            ['Value', currency(value)],
          ]} />
          <div style={{ display: 'grid', gap: 12 }}>
            {orders.map((order) => <OrderCard key={order.id} order={order} />)}
          </div>
        </>
      )}
    </main>
  )
}
