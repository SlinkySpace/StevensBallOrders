/**
 * Fails if anything under web/ can write to the database.
 *
 * The whole premise of this proof is that the Streamlit app keeps serving the
 * team while a second app reads the same rows. A stray INSERT here would write
 * to production, so the promise is enforced rather than asserted.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, extname, relative } from 'node:path'

const ROOT = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const SKIP = new Set(['node_modules', '.next', '.git'])
const EXTS = new Set(['.ts', '.tsx', '.js', '.mjs', '.jsx'])

// Word-boundary matches on SQL that changes data or schema.
const FORBIDDEN = [
  /\bINSERT\s+INTO\b/i,
  /\bUPDATE\s+\w+\s+SET\b/i,
  /\bDELETE\s+FROM\b/i,
  /\bDROP\s+(TABLE|DATABASE|COLUMN|INDEX)\b/i,
  /\bALTER\s+TABLE\b/i,
  /\bCREATE\s+(TABLE|INDEX|DATABASE)\b/i,
  /\bTRUNCATE\b/i,
  /\bUPSERT\b/i,
  /\bON\s+CONFLICT\b/i,
]

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    if (SKIP.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (EXTS.has(extname(entry))) out.push(full)
  }
  return out
}

const offences = []
for (const file of walk(ROOT)) {
  // The checker names the statements it looks for; it is not itself a writer.
  if (file.endsWith('assert-read-only.mjs')) continue
  const text = readFileSync(file, 'utf8')
  text.split('\n').forEach((line, i) => {
    for (const pattern of FORBIDDEN) {
      if (pattern.test(line)) {
        offences.push(`${relative(ROOT, file)}:${i + 1}  ${line.trim().slice(0, 90)}`)
      }
    }
  })
}

if (offences.length) {
  console.error('Write statements found - this app must stay read-only:\n')
  for (const o of offences) console.error('  ' + o)
  console.error(`\n${offences.length} offence(s).`)
  process.exit(1)
}

console.log(`Read-only check passed: no write statements in ${walk(ROOT).length} files.`)
