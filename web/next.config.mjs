/** @type {import('next').NextConfig} */
const nextConfig = {
  // Catalog images are served by app/static/[...path]/route.ts, which reads
  // them out of the Python app's static/ directory - one set of files, owned by
  // the refresh workflow rather than duplicated here.
  //
  // Note: the repo sits under OneDrive, so the first compile is slow; .next is
  // thousands of small files OneDrive syncs as they are written.
}
export default nextConfig
