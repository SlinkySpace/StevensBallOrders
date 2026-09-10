'use client'

/**
 * Session, cart and theme, shared by every screen.
 *
 * The cart lives on the server (db.saved_carts) so it survives a browser
 * change and so checkout can price it server-side. It is mirrored here for
 * responsiveness and written back on a short debounce - typing a quantity
 * should not be one request per keystroke.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react'
import { api, ApiError, type CartLine, type User } from '@/lib/api'

type Toast = { id: number; text: string; tone: 'ok' | 'bad' }

type AppState = {
  user: User | null
  isAdmin: boolean
  loading: boolean
  cart: CartLine[]
  theme: 'light' | 'dark'
  toasts: Toast[]
  refresh: () => Promise<void>
  setUser: (user: User | null, isAdmin: boolean) => void
  addToCart: (line: CartLine) => void
  updateLine: (index: number, patch: Partial<CartLine>) => void
  removeLine: (index: number) => void
  emptyCart: () => void
  clearCartLocal: () => void
  toggleTheme: () => void
  notify: (text: string, tone?: 'ok' | 'bad') => void
}

const Ctx = createContext<AppState | null>(null)

export function useApp(): AppState {
  const value = useContext(Ctx)
  if (!value) throw new Error('useApp must be used inside <Providers>')
  return value
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [cart, setCart] = useState<CartLine[]>([])
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [toasts, setToasts] = useState<Toast[]>([])

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dirty = useRef(false)

  const notify = useCallback((text: string, tone: 'ok' | 'bad' = 'ok') => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, text, tone }])
    setTimeout(() => setToasts((c) => c.filter((t) => t.id !== id)), 3600)
  }, [])

  // Theme: remembered per browser, applied to <html> so the CSS variables flip.
  useEffect(() => {
    let stored: string | null = null
    try {
      stored = window.localStorage.getItem('sb-theme')
    } catch {
      stored = null // private windows and blocked storage
    }
    const initial = stored === 'dark' || stored === 'light'
      ? stored
      : (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    setTheme(initial)
    document.documentElement.setAttribute('data-theme', initial)
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      document.documentElement.setAttribute('data-theme', next)
      try {
        window.localStorage.setItem('sb-theme', next)
      } catch {
        /* not worth failing a click over */
      }
      return next
    })
  }, [])

  const refresh = useCallback(async () => {
    try {
      const { user: me, is_admin } = await api.me()
      setUserState(me)
      setIsAdmin(is_admin)
      if (me) {
        const { cart: saved } = await api.cart()
        setCart(saved ?? [])
      } else {
        setCart([])
      }
    } catch (error) {
      setUserState(null)
      setIsAdmin(false)
      if (error instanceof ApiError && error.status === 0) notify(error.message, 'bad')
    } finally {
      setLoading(false)
    }
  }, [notify])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Push the cart back after edits settle. Marked dirty by the mutators below
  // so the initial load does not immediately write what it just read.
  useEffect(() => {
    if (!user || !dirty.current) return
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      dirty.current = false
      api.saveCart(cart).catch((error: unknown) => {
        notify(error instanceof Error ? error.message : 'Could not save the cart.', 'bad')
      })
    }, 500)
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    }
  }, [cart, user, notify])

  const mutate = useCallback((next: (current: CartLine[]) => CartLine[]) => {
    dirty.current = true
    setCart(next)
  }, [])

  const addToCart = useCallback((line: CartLine) => {
    mutate((current) => {
      // Same product and same option is the same line; bump it rather than
      // stacking duplicates the shopper then has to tidy up.
      const at = current.findIndex(
        (existing) =>
          existing.product_url === line.product_url &&
          existing.option_value === line.option_value,
      )
      if (at === -1) return [...current, line]
      const copy = [...current]
      copy[at] = {
        ...copy[at],
        quantity: Math.min(20, copy[at].quantity + line.quantity),
        note: line.note || copy[at].note,
      }
      return copy
    })
  }, [mutate])

  const updateLine = useCallback((index: number, patch: Partial<CartLine>) => {
    mutate((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)))
  }, [mutate])

  const removeLine = useCallback((index: number) => {
    mutate((current) => current.filter((_, i) => i !== index))
  }, [mutate])

  const emptyCart = useCallback(() => mutate(() => []), [mutate])

  // After checkout the server has already cleared it; do not write back an
  // empty cart over an order that was just placed.
  const clearCartLocal = useCallback(() => {
    dirty.current = false
    setCart([])
  }, [])

  const setUser = useCallback((next: User | null, admin: boolean) => {
    setUserState(next)
    setIsAdmin(admin)
  }, [])

  const value = useMemo<AppState>(() => ({
    user, isAdmin, loading, cart, theme, toasts,
    refresh, setUser, addToCart, updateLine, removeLine,
    emptyCart, clearCartLocal, toggleTheme, notify,
  }), [user, isAdmin, loading, cart, theme, toasts, refresh, setUser,
       addToCart, updateLine, removeLine, emptyCart, clearCartLocal, toggleTheme, notify])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
