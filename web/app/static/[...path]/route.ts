/**
 * Serves the catalog images out of the Python app's static/ directory.
 *
 * They are committed there by the refresh workflow. Copying 12MB of webp into
 * web/public would mean two sets of the same files drifting apart every time
 * the scraper runs, and a Windows symlink needs developer mode - so this reads
 * them directly.
 *
 * For a deployment where the web app is its own Vercel project rooted at web/,
 * these files sit outside that root. Either enable "Include files outside the
 * root directory", or point image_url at a CDN.
 */

import { readFile, stat } from 'node:fs/promises'
import { extname, join, normalize, resolve } from 'node:path'
import { NextResponse } from 'next/server'

const STATIC_ROOT = resolve(process.cwd(), '..', 'static')

const CONTENT_TYPES: Record<string, string> = {
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  const relative = normalize(path.join('/'))

  // Refuse anything that climbs out of static/, however it is spelled.
  const absolute = resolve(join(STATIC_ROOT, relative))
  if (!absolute.startsWith(STATIC_ROOT)) {
    return new NextResponse('Not found', { status: 404 })
  }

  const type = CONTENT_TYPES[extname(absolute).toLowerCase()]
  if (!type) return new NextResponse('Not found', { status: 404 })

  try {
    const info = await stat(absolute)
    if (!info.isFile()) return new NextResponse('Not found', { status: 404 })
    const body = await readFile(absolute)
    return new NextResponse(new Uint8Array(body), {
      headers: {
        'Content-Type': type,
        'Content-Length': String(info.size),
        'Cache-Control': 'public, max-age=3600',
      },
    })
  } catch {
    return new NextResponse('Not found', { status: 404 })
  }
}
