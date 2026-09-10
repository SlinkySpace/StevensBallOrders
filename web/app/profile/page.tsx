'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Chrome } from '@/components/Chrome'
import { Stats } from '@/components/OrderCard'
import { useApp } from '@/app/providers'
import { api, ApiError, type Order } from '@/lib/api'
import { currency, initials } from '@/lib/format'

const ACTIVE = ['submitted', 'approved', 'ordered']

export default function ProfilePage() {
  return <Chrome><Profile /></Chrome>
}

function Profile() {
  const { user, refresh, setUser, notify } = useApp()
  const router = useRouter()
  const [orders, setOrders] = useState<Order[]>([])
  const [card, setCard] = useState(user?.saved_card ?? '')
  const [passwords, setPasswords] = useState({ current: '', next: '', confirm: '' })
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.orders().then(({ orders: mine }) => setOrders(mine)).catch(() => { /* stats only */ })
  }, [])

  useEffect(() => { setCard(user?.saved_card ?? '') }, [user?.saved_card])

  if (!user) return null

  const outstanding = orders.filter((o) => ACTIVE.includes(String(o.status).toLowerCase())).length
  const fulfilled = orders.filter((o) => String(o.status).toLowerCase() === 'fulfilled').length

  async function saveCard() {
    try {
      await api.savedCard(card)
      await refresh()
      notify('Saved card updated.')
    } catch (error) {
      notify(error instanceof ApiError ? error.message : 'Could not save.', 'bad')
    }
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await api.changePassword(passwords.current, passwords.next, passwords.confirm)
      setPasswords({ current: '', next: '', confirm: '' })
      notify('Password updated.')
    } catch (error) {
      notify(error instanceof ApiError ? error.message : 'Could not change the password.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    try {
      await api.logout()
    } finally {
      // Clear locally either way: if the cookie is already gone the call fails
      // but the user is just as signed out.
      setUser(null, false)
      router.replace('/signin')
    }
  }

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '36px 28px 80px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18, marginBottom: 28 }}>
        <div style={{
          width: 60, height: 60, borderRadius: '50%', background: 'var(--soft)',
          border: '1px solid rgba(163,38,56,0.28)', display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          font: '800 20px/1 Archivo, sans-serif', color: 'var(--ink)', flex: 'none',
        }}>{initials(user.first_name, user.last_name)}</div>
        <div>
          <h1 style={{
            font: '800 clamp(26px, 2.6vw, 34px)/1 Archivo, sans-serif',
            letterSpacing: '-0.03em', margin: '0 0 6px',
          }}>{user.first_name} {user.last_name}</h1>
          <div style={{ fontSize: 14, color: 'var(--dim)' }}>{user.email}</div>
        </div>
      </div>

      <Stats figures={[
        ['Outstanding orders', String(outstanding)],
        ['Fulfilled orders', String(fulfilled)],
        ['Balance owed', currency(user.balance_owed)],
      ]} />

      <div className="profile-grid" style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, alignItems: 'start',
      }}>
        <div className="card" style={{ padding: 22 }}>
          <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 16 }}>Payment</div>
          <label className="label">Saved card placeholder</label>
          <input className="field" value={card} onChange={(e) => setCard(e.target.value)}
                 style={{ marginBottom: 14 }} />
          <button className="btn-quiet" style={{ color: 'var(--text)' }} onClick={saveCard}>
            Update saved card placeholder
          </button>
        </div>

        <form className="card" style={{ padding: 22 }} onSubmit={changePassword}>
          <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 16 }}>
            Change password
          </div>
          <div style={{ display: 'grid', gap: 12 }}>
            <div>
              <label className="label">Current password</label>
              <input className="field" type="password" required autoComplete="current-password"
                     value={passwords.current}
                     onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} />
            </div>
            <div>
              <label className="label">New password</label>
              <input className="field" type="password" required autoComplete="new-password"
                     value={passwords.next}
                     onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} />
              <div style={{ fontSize: 12, color: 'var(--dim2)', marginTop: 6 }}>
                At least 8 characters.
              </div>
            </div>
            <div>
              <label className="label">Confirm new password</label>
              <input className="field" type="password" required autoComplete="new-password"
                     value={passwords.confirm}
                     onChange={(e) => setPasswords({ ...passwords, confirm: e.target.value })} />
            </div>
            <button className="btn" type="submit" disabled={busy}
                    style={{ padding: '11px 16px', fontSize: 14, marginTop: 2 }}>
              {busy ? 'Updating…' : 'Update password'}
            </button>
          </div>
        </form>
      </div>

      <button className="btn-quiet" style={{ marginTop: 24 }} onClick={logout}>Log out</button>

      <style>{`
        @media (max-width: 780px) {
          .profile-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
  )
}
