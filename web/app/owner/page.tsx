'use client'

import { useCallback, useEffect, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { OrderCard, Stats } from '@/components/OrderCard'
import { useApp } from '@/app/providers'
import { api, ApiError, type Dashboard } from '@/lib/api'
import { currency, downloadCsv, ordersToCsv } from '@/lib/format'

const ALL_STATUSES = ['submitted', 'approved', 'ordered', 'fulfilled', 'cancelled']

export default function OwnerPage() {
  return <Chrome><Owner /></Chrome>
}

function Owner() {
  const { isAdmin, notify } = useApp()
  const [data, setData] = useState<Dashboard | null>(null)
  const [statuses, setStatuses] = useState<string[]>(ALL_STATUSES)
  const [bulk, setBulk] = useState('submitted')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (wanted: string[]) => {
    try {
      setData(await api.dashboard(wanted))
    } catch (error) {
      notify(error instanceof ApiError ? error.message : 'Could not load the dashboard.', 'bad')
    } finally {
      setLoading(false)
    }
  }, [notify])

  useEffect(() => { void load(statuses) }, [load, statuses])

  if (!isAdmin) {
    return (
      <main style={{ maxWidth: 900, margin: '0 auto', padding: '36px 28px 80px' }}>
        <h1 className="h1">Owner Dashboard</h1>
        <p className="sub">Owners only. Ask a captain if you need access.</p>
      </main>
    )
  }

  if (loading || !data) {
    return (
      <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
        <div style={{ color: 'var(--dim)', fontSize: 14 }}>Loading…</div>
      </main>
    )
  }

  const passwordless = data.users.filter((u) => !u.has_password)

  async function act(work: Promise<unknown>, message: string) {
    try {
      await work
      notify(message)
      await load(statuses)
    } catch (error) {
      notify(error instanceof ApiError ? error.message : 'That did not work.', 'bad')
    }
  }

  return (
    <main style={{ maxWidth: 1320, margin: '0 auto', padding: '36px 28px 80px' }}>
      <h1 className="h1">Owner Dashboard</h1>
      <p className="sub">Everyone&apos;s orders, and what still needs placing.</p>

      {passwordless.length > 0 && (
        <div style={{
          display: 'flex', gap: 12, padding: '14px 18px',
          border: '1px solid rgba(214,158,46,0.4)', background: 'rgba(214,158,46,0.11)',
          borderRadius: 12, marginBottom: 22, fontSize: 14, lineHeight: 1.55,
        }}>
          <span style={{ fontSize: 16 }}>⚠️</span>
          <div>
            <strong>{passwordless.length} account(s) have not set a password yet.</strong>{' '}
            Until each one does, anyone who knows the email address can claim it.
          </div>
        </div>
      )}

      <div className="stats" style={{ marginBottom: 24 }}>
        <div>
          <div className="stat-label">Pending bowling balls</div>
          <div className="stat-value">{data.pending_ball_count}</div>
        </div>
        <div>
          <div className="stat-label">Pending orders</div>
          <div className="stat-value stat-value--accent">{data.active_order_count}</div>
        </div>
        <div style={{
          flex: 1, minWidth: 220, display: 'flex', alignItems: 'center',
          justifyContent: 'flex-end',
        }}>
          <div style={{
            fontSize: 13, color: 'var(--dim)', textAlign: 'right', maxWidth: '34ch',
          }}>
            Owners are emailed once {data.ball_batch_threshold} balls are waiting in
            submitted or approved.
          </div>
        </div>
      </div>

      <section className="card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 6 }}>
          Pending bowling ball summary
        </div>
        <div style={{ fontSize: 13, color: 'var(--dim)', marginBottom: 16 }}>
          Grouped by ball and weight — this is the list to place with Storm.
        </div>
        {data.grouped_balls.length === 0 ? (
          <div style={{ fontSize: 14, color: 'var(--dim)' }}>
            No bowling balls are waiting to be ordered.
          </div>
        ) : (
          <div className="rows">
            <div className="rows__head" style={{
              gridTemplateColumns: 'minmax(0, 2fr) 1fr 90px 90px',
            }}>
              <div>Product</div><div>SKU</div>
              <div className="right">Weight</div><div className="right">Qty</div>
            </div>
            {data.grouped_balls.map((row, index) => (
              <div key={index} className="rows__row" style={{
                gridTemplateColumns: 'minmax(0, 2fr) 1fr 90px 90px',
              }}>
                <div>
                  <div>{row.product_name}</div>
                  {/* Who it is for. The owner places one batch with Storm and
                      then has to split it, so the names belong next to the count. */}
                  {row.customers && (
                    <div style={{ fontSize: 11, color: 'var(--dim2)', marginTop: 3 }}>
                      {row.customers}
                    </div>
                  )}
                </div>
                <div className="mono">{row.sku || '—'}</div>
                <div className="right">{row.option_value || '—'}</div>
                <div className="right num" style={{ fontWeight: 700 }}>{row.total_qty}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 14 }}>
          Order management
        </div>

        <div className="owner-filters" style={{
          display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) 1fr',
          gap: 16, alignItems: 'end', marginBottom: 16,
        }}>
          <div>
            <label className="label">Show orders with these statuses</label>
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
              {ALL_STATUSES.map((statusName) => {
                const on = statuses.includes(statusName)
                return (
                  <button key={statusName} onClick={() => setStatuses(
                    on ? statuses.filter((s) => s !== statusName) : [...statuses, statusName],
                  )} style={{
                    padding: '7px 12px', borderRadius: 999, cursor: 'pointer',
                    border: `1px solid ${on ? 'var(--primary)' : 'var(--border)'}`,
                    background: on ? 'var(--soft)' : 'transparent',
                    color: on ? 'var(--ink)' : 'var(--dim)',
                    font: `${on ? 700 : 600} 12px/1 'Source Sans 3', sans-serif`,
                    textTransform: 'capitalize',
                  }}>{statusName}</button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="label">Bulk update filtered orders to</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <select className="field" value={bulk} onChange={(e) => setBulk(e.target.value)}
                      style={{ flex: 1, cursor: 'pointer', textTransform: 'capitalize' }}>
                {ALL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="btn" style={{ padding: '10px 14px', fontSize: 13 }}
                      disabled={data.orders.length === 0}
                      onClick={() => {
                        const ids = data.orders.map((o) => o.id)
                        if (!confirm(`Set ${ids.length} order(s) to "${bulk}"?`)) return
                        void act(api.bulkStatus(ids, bulk), `${ids.length} order(s) set to ${bulk}.`)
                      }}>Apply to all shown</button>
            </div>
          </div>
        </div>

        <div style={{ fontSize: 13, color: 'var(--dim2)', marginBottom: 14 }}>
          {data.orders.length} order{data.orders.length === 1 ? '' : 's'} shown
        </div>

        <div style={{ display: 'grid', gap: 12 }}>
          {data.orders.map((order) => (
            <OrderCard key={order.id} order={order} showCustomer defaultOpen extra={
              <StatusControls
                current={order.status}
                onApply={(next) => act(
                  api.setOrderStatus(order.id, next),
                  `Order #${order.id} set to ${next}.`,
                )}
                onDelete={() => {
                  if (!confirm(`Delete order #${order.id}? This cannot be undone.`)) return
                  void act(api.deleteOrder(order.id), `Order #${order.id} deleted.`)
                }}
              />
            } />
          ))}
        </div>

        {data.orders.length > 0 && (
          <button className="btn-quiet" style={{ marginTop: 16, color: 'var(--text)', fontSize: 13 }}
                  onClick={() => downloadCsv('orders_export.csv', ordersToCsv(data.orders))}>
            Export shown orders to CSV
          </button>
        )}
      </section>

      <section className="card" style={{ padding: 20 }}>
        <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 6 }}>User balances</div>
        <div style={{
          fontSize: 13, color: 'var(--dim)', marginBottom: 16, maxWidth: '76ch',
        }}>
          Reset password clears the account&apos;s password so it can be set again from
          the &quot;First time here?&quot; tab. Orders and balance are untouched.
        </div>
        <div className="rows">
          {data.users.map((teamUser) => (
            <UserRow key={teamUser.id} user={teamUser}
                     onSave={(balance) => act(
                       api.setBalance(teamUser.id, balance),
                       `${teamUser.first_name}'s balance saved.`,
                     )}
                     onReset={() => {
                       if (!confirm(`Clear ${teamUser.email}'s password?`)) return
                       void act(api.resetPassword(teamUser.id), 'Password cleared.')
                     }} />
          ))}
        </div>
        <button className="btn-quiet" style={{ marginTop: 16, color: 'var(--text)', fontSize: 13 }}
                onClick={() => act(api.recheckBallBatch(), 'Batch notification re-checked.')}>
          Re-check bowling ball batch notification
        </button>
      </section>

      <style>{`
        @media (max-width: 820px) {
          .owner-filters { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
  )
}

function StatusControls({ current, onApply, onDelete }: {
  current: string; onApply: (next: string) => void; onDelete: () => void
}) {
  const [next, setNext] = useState(current)
  return (
    <>
      <label className="label label--sm">Update status</label>
      <select className="field field--sm" value={next} onChange={(e) => setNext(e.target.value)}
              style={{ background: 'var(--bg2)', cursor: 'pointer', textTransform: 'capitalize' }}>
        {ALL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <button onClick={() => onApply(next)} style={{
        width: '100%', padding: 9, border: 0, borderRadius: 7,
        background: 'var(--text)', color: 'var(--bg)',
        font: "700 13px/1 'Source Sans 3', sans-serif", cursor: 'pointer',
      }}>Apply status</button>
      <button onClick={onDelete} className="btn-quiet" style={{
        width: '100%', padding: 9, borderRadius: 7, fontSize: 13,
      }}>Delete order</button>
    </>
  )
}

function UserRow({ user, onSave, onReset }: {
  user: import('@/lib/api').TeamUser
  onSave: (balance: number) => void
  onReset: () => void
}) {
  const [balance, setBalance] = useState(String(user.balance_owed ?? 0))
  useEffect(() => { setBalance(String(user.balance_owed ?? 0)) }, [user.balance_owed])

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1.1fr) minmax(0, 1.4fr) 104px 68px 122px',
      gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--border)',
      alignItems: 'center',
    }}>
      <div style={{ fontWeight: 600, fontSize: 14 }}>
        {user.first_name} {user.last_name}
      </div>
      <div style={{
        fontSize: 13, color: 'var(--dim)', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {user.email}
        {!user.has_password && (
          <span style={{ color: 'var(--ink)', fontWeight: 600 }}> · no password</span>
        )}
      </div>
      <input className="field field--sm num" type="number" step="1" value={balance}
             onChange={(e) => setBalance(e.target.value)} />
      <button onClick={() => onSave(Number(balance) || 0)} style={{
        padding: 8, border: 0, borderRadius: 7, background: 'var(--text)', color: 'var(--bg)',
        font: "700 12px/1 'Source Sans 3', sans-serif", cursor: 'pointer',
      }}>Save</button>
      <button onClick={onReset} className="btn-quiet" style={{
        padding: 8, borderRadius: 7, fontSize: 12,
        opacity: user.has_password ? 1 : 0.45,
      }} disabled={!user.has_password}>Reset password</button>
    </div>
  )
}
