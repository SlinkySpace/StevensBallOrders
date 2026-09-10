import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'

export const metadata: Metadata = {
  title: 'Stevens Bowling Team Orders',
  description: 'Order Storm gear at team price.',
}

/**
 * Sets data-theme before first paint.
 *
 * Without it the page renders light, then flips to dark once React mounts,
 * which is a visible flash on every navigation for anyone using dark mode.
 * Wrapped in try/catch because localStorage throws outright in some privacy
 * modes rather than returning null.
 */
const THEME_BOOT = `
(function () {
  try {
    var stored = localStorage.getItem('sb-theme');
    var dark = stored ? stored === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
`

/*
 * suppressHydrationWarning on <html>: THEME_BOOT rewrites data-theme before
 * React hydrates, so the server's "light" and the client's actual theme
 * legitimately differ. That mismatch is the whole point - without the script
 * there is a light flash on every load for anyone using dark mode - and the
 * suppression is scoped to this one element's attributes, not its children.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800&family=Source+Sans+3:wght@400;600;700&family=Source+Code+Pro:wght@400;600&display=swap"
        />
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
