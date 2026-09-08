/** @type {import('next').NextConfig} */
const nextConfig = {
  // Catalog images are served by app/static/[...path]/route.ts, which reads
  // them out of the Python app's static/ directory.
  //
  // Note: the repo lives under OneDrive, so the first compile is slow - .next
  // is thousands of small files OneDrive syncs as they are written. distDir
  // cannot move it out, since Next resolves that path relative to the project
  // root. Excluding web/.next in the OneDrive settings is the way to fix it.
}
export default nextConfig
