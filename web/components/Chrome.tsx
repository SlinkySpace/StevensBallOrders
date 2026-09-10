'use client'

/**
 * The signed-in shell: bowling-ball mark, balance pill, theme toggle, cart
 * button, and the nav row — straight from the design.
 *
 * It also decides what a signed-out visitor sees. Every screen but the sign-in
 * page renders inside this, so the redirect lives here once rather than in
 * eight pages.
 */

import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useApp } from '@/app/providers'
import { currency, cartUnits } from '@/lib/format'

export function BallMark({ size = 22 }: { size?: number }) {
  const dot = size * 0.16
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: 'var(--primary)', position: 'relative', flex: 'none',
    }}>
      {[[0.27, 0.27], [0.55, 0.23], [0.41, 0.55]].map(([x, y], i) => (
        <div key={i} style={{
          position: 'absolute', left: size * x, top: size * y,
          width: dot, height: dot, borderRadius: '50%',
          background: 'rgba(0,0,0,0.55)',
        }} />
      ))}
    </div>
  )
}

const NAV = [
  { href: '/', label: 'Catalog' },
  { href: '/cart', label: 'Cart' },
  { href: '/checkout', label: 'Checkout' },
  { href: '/outstanding', label: 'Outstanding Orders' },
  { href: '/history', label: 'Order History' },
  { href: '/profile', label: 'Profile' },
]

const ADMIN_NAV = [{ href: '/owner', label: 'Owner Dashboard' }]

export function Chrome({ children }: { children: React.ReactNode }) {
  const { user, isAdmin, loading, cart, theme, toggleTheme, toasts } = useApp()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (!loading && !user) router.replace('/signin')
  }, [loading, user, router])

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center',
        justifyContent: 'center', color: 'var(--dim)',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ display: 'inline-block', marginBottom: 14 }}><BallMark size={30} /></div>
          <div style={{ fontSize: 14 }}>Loading…</div>
        </div>
      </div>
    )
  }

  if (!user) return null // the redirect above is already on its way

  const balance = Number(user.balance_owed || 0)
  const units = cartUnits(cart)
  const items = [...NAV, ...(isAdmin ? ADMIN_NAV : [])]

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>
      <header style={{
        position: 'sticky', top: 0, zIndex: 40,
        background: 'var(--bg)', borderBottom: '1px solid var(--border)',
      }}>
        <div style={{
          maxWidth: 1320, margin: '0 auto', padding: '0 28px',
          display: 'flex', alignItems: 'center', gap: 20, height: 60,
        }}>
          <a href="/" style={{
            display: 'flex', alignItems: 'center', gap: 10,
            cursor: 'pointer', flex: 'none', color: 'inherit', textDecoration: 'none',
          }}>
            <BallMark />
            <div style={{
              font: '800 13px/1 Archivo, sans-serif', letterSpacing: '0.14em',
              textTransform: 'uppercase', whiteSpace: 'nowrap',
            }}>Stevens Bowling</div>
          </a>

          <div style={{ flex: 1 }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 9, flex: 'none' }}>
            {balance > 0 && (
              <a href="/profile" style={{
                display: 'flex', alignItems: 'baseline', gap: 7, padding: '7px 12px',
                borderRadius: 999, background: 'var(--soft)',
                border: '1px solid rgba(163,38,56,0.28)', cursor: 'pointer',
                whiteSpace: 'nowrap', textDecoration: 'none',
              }}>
                <span style={{
                  font: "600 10px/1 'Source Sans 3', sans-serif", letterSpacing: '0.1em',
                  textTransform: 'uppercase', color: 'var(--ink)',
                }}>You owe</span>
                <span className="num" style={{
                  font: "700 14px/1 'Source Sans 3', sans-serif", color: 'var(--ink)',
                }}>{currency(balance)}</span>
              </a>
            )}

            <button onClick={toggleTheme} title="Toggle light or dark" style={{
              height: 36, flex: 'none', padding: '0 13px', display: 'flex',
              alignItems: 'center', justifyContent: 'center', background: 'transparent',
              border: '1px solid var(--border)', borderRadius: 9, color: 'var(--dim)',
              cursor: 'pointer', font: "600 13px/1 'Source Sans 3', sans-serif",
            }}>{theme === 'dark' ? '☀' : '☾'}</button>

            <a href="/cart" style={{
              display: 'flex', alignItems: 'center', gap: 8, flex: 'none',
              background: 'var(--text)', color: 'var(--bg)', borderRadius: 9,
              padding: '0 14px', height: 36, font: "700 13px/1 'Source Sans 3', sans-serif",
              cursor: 'pointer', whiteSpace: 'nowrap', textDecoration: 'none',
            }}>
              <span style={{ fontSize: 14 }}>🛒</span>
              <span>{units ? `Cart · ${units}` : 'Cart'}</span>
            </a>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)' }}>
          <nav style={{
            maxWidth: 1320, margin: '0 auto', padding: '6px 20px',
            display: 'flex', alignItems: 'center', gap: 2, overflowX: 'auto',
          }}>
            {items.map((item) => {
              const active = pathname === item.href
              return (
                <a key={item.href} href={item.href} style={{
                  padding: '8px 13px', borderRadius: 8, whiteSpace: 'nowrap',
                  textDecoration: 'none',
                  font: `${active ? 700 : 600} 13px/1 'Source Sans 3', sans-serif`,
                  color: active ? 'var(--ink)' : 'var(--dim)',
                  background: active ? 'var(--soft)' : 'transparent',
                }}>{item.label}</a>
              )
            })}
          </nav>
        </div>

        <div style={{ height: 3, background: 'var(--primary)', opacity: 0.9 }} />
      </header>

      {children}

      <div style={{
        position: 'fixed', right: 20, bottom: 20, zIndex: 90,
        display: 'grid', gap: 8, justifyItems: 'end',
      }}>
        {toasts.map((toast) => (
          <div key={toast.id} style={{
            animation: 'toastin 0.16s ease-out',
            background: 'var(--card)', color: 'var(--text)',
            border: `1px solid ${toast.tone === 'bad' ? 'var(--primary)' : 'var(--border)'}`,
            borderLeft: `3px solid ${toast.tone === 'bad' ? 'var(--primary)' : 'var(--accent)'}`,
            borderRadius: 10, padding: '11px 15px', maxWidth: 380,
            boxShadow: '0 14px 34px rgba(0,0,0,0.18)',
            font: "600 13px/1.45 'Source Sans 3', sans-serif",
          }}>{toast.text}</div>
        ))}
      </div>
    </div>
  )
}
