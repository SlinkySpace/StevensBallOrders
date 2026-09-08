/** @type {import('next').NextConfig} */
const nextConfig = {
  // The catalog images live in the Python app's static/ directory and are
  // committed by the refresh workflow. Served from there rather than copied,
  // so there is one set of files and the scraper keeps owning them.
  async rewrites() {
    return [{ source: '/catalog-images/:path*', destination: '/catalog-images/:path*' }]
  },
}
export default nextConfig
