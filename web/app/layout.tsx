import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Team Bowling Order Dashboard',
  description: 'Read-only proof rendered outside Streamlit, against the same database.',
}

const NAV = [
  { href: '/', label: 'Catalog' },
  { href: '/orders', label: 'Orders' },
  { href: '/signin', label: 'Sign-in check' },
]

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <h1>🎳 Team Bowling Order Dashboard</h1>
            <div className="who">read-only proof · Next.js</div>
            <nav>
              {NAV.map((item) => (
                <a key={item.href} href={item.href}>{item.label}</a>
              ))}
            </nav>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  )
}
