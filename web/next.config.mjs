/**
 * The API is a separate Vercel project, so it is a separate origin - and
 * *.vercel.app is on the Public Suffix List, which makes two subdomains of it
 * cross-site, not merely cross-origin. The session is an HttpOnly SameSite=Lax
 * cookie, and Lax cookies are not sent on cross-site requests at all: signing
 * in would appear to work and every request after it would be anonymous.
 *
 * SameSite=None would send it, at the cost of depending on third-party cookies
 * - which Safari blocks outright, so the app would be broken on every iPhone
 * on the team.
 *
 * Proxying instead keeps the browser on one origin. The cookie stays Lax and
 * first-party, there is no preflight, and CORS_ORIGINS stops mattering. The
 * cost is one extra hop per request, which for a team of a few dozen is not
 * worth trading correctness for.
 *
 * /static is proxied for the same reason it is served by the API at all: the
 * catalog images live in static/ at the repo root, outside this project's root
 * directory, and copying 12MB in here would mean two sets drifting apart on
 * every scrape.
 */
const API_ORIGIN = (
  process.env.API_ORIGIN
  // Deployed, the API is its own project on this team. Defaulted rather than
  // required as an environment variable: the two projects are halves of one
  // repo and this URL is not a secret, so making a fresh deploy depend on
  // someone remembering to set it only buys a broken frontend that builds.
  || (process.env.VERCEL ? 'https://api-stevens-bowling.vercel.app' : 'http://localhost:8000')
).replace(/\/$/, '')

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${API_ORIGIN}/api/:path*` },
      { source: '/static/:path*', destination: `${API_ORIGIN}/static/:path*` },
    ]
  },
}
export default nextConfig
