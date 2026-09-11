'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useApp } from '@/app/providers'
import { api, ApiError } from '@/lib/api'
import { BallMark } from '@/components/Chrome'

type Tab = 'login' | 'signup' | 'claim'

export default function SignInPage() {
  const { user, loading, refresh, notify } = useApp()
  const router = useRouter()
  const [tab, setTab] = useState<Tab>('login')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [form, setForm] = useState({
    email: '', password: '', confirm: '',
    first_name: '', last_name: '', access_code: '',
  })
  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  useEffect(() => {
    if (!loading && user) router.replace('/')
  }, [loading, user, router])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (tab === 'login') {
        await api.login(form.email, form.password)
      } else if (tab === 'signup') {
        await api.signup({
          first_name: form.first_name, last_name: form.last_name, email: form.email,
          password: form.password, confirm: form.confirm, access_code: form.access_code,
        })
      } else {
        await api.claim({
          email: form.email, password: form.password,
          confirm: form.confirm, access_code: form.access_code,
        })
      }
      await refresh()
      notify('Signed in.')
      router.replace('/')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const tabStyle = (which: Tab): React.CSSProperties => ({
    flex: 1, padding: '9px 8px', borderRadius: 7, border: 0, cursor: 'pointer',
    font: `${tab === which ? 700 : 600} 13px/1 'Source Sans 3', sans-serif`,
    background: tab === which ? 'var(--card)' : 'transparent',
    color: tab === which ? 'var(--text)' : 'var(--dim)',
    boxShadow: tab === which ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
  })

  return (
    <div style={{
      minHeight: '100vh', display: 'grid',
      gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)', alignItems: 'stretch',
    }} className="signin-grid">
      <div style={{
        position: 'relative', overflow: 'hidden', background: 'var(--bg2)',
        padding: '56px 56px 48px', display: 'flex', flexDirection: 'column',
        justifyContent: 'space-between', minHeight: '100vh',
      }}>
        {/* Lane rings and boards - decorative, straight from the design. */}
        <div className="lanes" style={{ inset: '-30% -40% auto auto', width: 820, height: 820 }} />
        <div style={{
          position: 'absolute', left: 0, right: 0, bottom: 0, height: '38%',
          background: 'repeating-linear-gradient(90deg, var(--lane) 0 1px, transparent 1px 72px)',
          pointerEvents: 'none',
        }} />

        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 10 }}>
          <BallMark />
          <div style={{
            font: '800 13px/1 Archivo, sans-serif', letterSpacing: '0.16em',
            textTransform: 'uppercase',
          }}>Stevens Bowling</div>
        </div>

        <div style={{ position: 'relative', maxWidth: 520 }}>
          <div className="eyebrow" style={{ marginBottom: 18 }}>Sponsor pricing · members only</div>
          <h1 style={{
            font: '800 clamp(38px, 4.4vw, 62px)/0.98 Archivo, sans-serif',
            letterSpacing: '-0.03em', margin: '0 0 18px',
          }}>Order Storm gear<br />at team price.</h1>
          <p style={{
            fontSize: 17, lineHeight: 1.55, color: 'var(--dim)',
            margin: '0 0 28px', maxWidth: '44ch',
          }}>
            Pick out what you want, and the Eboard will put it all in as one order.
            Sign in with your Stevens email.
          </p>
        </div>

        <div style={{ position: 'relative', fontSize: 13, color: 'var(--dim2)' }}>
          Storm equipment is ordered through the team&apos;s sponsor account.
        </div>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '48px 40px', background: 'var(--bg)',
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <div style={{
            display: 'flex', gap: 4, padding: 4, background: 'var(--bg2)',
            border: '1px solid var(--border)', borderRadius: 10, marginBottom: 26,
          }}>
            <button onClick={() => { setTab('login'); setError('') }} style={tabStyle('login')}>Login</button>
            <button onClick={() => { setTab('signup'); setError('') }} style={tabStyle('signup')}>Create account</button>
            <button onClick={() => { setTab('claim'); setError('') }} style={tabStyle('claim')}>First time?</button>
          </div>

          <h2 style={{
            font: '700 24px/1.2 Archivo, sans-serif', letterSpacing: '-0.02em',
            margin: '0 0 6px',
          }}>
            {tab === 'login' ? 'Welcome back'
              : tab === 'signup' ? 'Create account' : 'First time here?'}
          </h2>
          <p style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--dim)', margin: '0 0 24px' }}>
            {tab === 'login' ? 'Email and password, same as always.'
              : tab === 'signup' ? "Ask Eboard for the team access code - you'll need it below."
              : 'Your account is older than the password screen. Pick one here and everything you have already ordered stays put.'}
          </p>

          <form onSubmit={submit} style={{ display: 'grid', gap: 16 }}>
            {tab === 'signup' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label className="label">First name</label>
                  <input className="field" value={form.first_name} onChange={set('first_name')} autoComplete="given-name" />
                </div>
                <div>
                  <label className="label">Last name</label>
                  <input className="field" value={form.last_name} onChange={set('last_name')} autoComplete="family-name" />
                </div>
              </div>
            )}

            <div>
              <label className="label">Email</label>
              <input className="field" type="email" value={form.email} onChange={set('email')} autoComplete="email" required />
            </div>

            <div>
              <label className="label">{tab === 'claim' ? 'Choose a password' : 'Password'}</label>
              <input className="field" type="password" value={form.password} onChange={set('password')}
                     autoComplete={tab === 'login' ? 'current-password' : 'new-password'} required />
              {tab !== 'login' && (
                <div style={{ fontSize: 12, color: 'var(--dim2)', marginTop: 6 }}>At least 8 characters.</div>
              )}
            </div>

            {tab !== 'login' && (
              <>
                <div>
                  <label className="label">Confirm password</label>
                  <input className="field" type="password" value={form.confirm}
                         onChange={set('confirm')} autoComplete="new-password" required />
                </div>
                <div>
                  <label className="label">Team access code</label>
                  <input className="field" type="password" value={form.access_code}
                         onChange={set('access_code')} />
                </div>
              </>
            )}

            {error && (
              <div role="alert" style={{
                padding: '11px 13px', borderRadius: 8,
                border: '1px solid rgba(163,38,56,0.35)', background: 'var(--soft)',
                color: 'var(--ink)', fontSize: 13, lineHeight: 1.5,
              }}>{error}</div>
            )}

            <button className="btn" type="submit" disabled={busy} style={{ marginTop: 4 }}>
              {busy ? 'Working…'
                : tab === 'login' ? 'Login'
                : tab === 'signup' ? 'Create account' : 'Set password and log in'}
            </button>
          </form>

          {tab === 'login' && (
            <div style={{
              marginTop: 20, padding: '12px 14px', border: '1px solid var(--border)',
              borderRadius: 8, background: 'var(--bg2)', fontSize: 13,
              lineHeight: 1.5, color: 'var(--dim)',
            }}>
              Account made before passwords existed? Open{' '}
              <strong style={{ color: 'var(--text)' }}>First time?</strong> to set one —
              orders and balance stay put.
            </div>
          )}
        </div>
      </div>

      <style>{`
        @media (max-width: 860px) {
          .signin-grid { grid-template-columns: 1fr !important; }
          .signin-grid > div:first-child { min-height: auto !important; padding: 32px 28px !important; }
        }
      `}</style>
    </div>
  )
}
