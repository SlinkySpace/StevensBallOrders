/**
 * The cutover check: every hash Python wrote must verify in Node, and every
 * hash Node writes must verify in Python.
 *
 * Test passwords are generated here; no real account's password or hash is
 * used. Python's side of the exchange is produced by password-compat-fixtures.py.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { verifyPassword, hashPassword } from '../lib/password.ts'

const here = dirname(fileURLToPath(import.meta.url))
const fixtures = JSON.parse(readFileSync(join(here, 'password-fixtures.json'), 'utf8')) as {
  cases: { password: string; hash: string; note: string }[]
}

let passed = 0
let failed = 0

function check(label: string, ok: boolean, extra = '') {
  if (ok) { passed++; console.log(`PASS  ${label}`) }
  else { failed++; console.log(`FAIL  ${label}${extra ? `\n        ${extra}` : ''}`) }
}

console.log('== Python-generated hashes verify in Node ==')
for (const c of fixtures.cases) {
  check(`${c.note}`, await verifyPassword(c.password, c.hash))
  check(`${c.note} - wrong password rejected`,
    !(await verifyPassword(c.password + 'x', c.hash)))
}

console.log('\n== malformed input is rejected, not thrown on ==')
const junk = [
  ['empty string', ''],
  ['no dollar separators', 'notahash'],
  ['too few fields', 'pbkdf2_sha256$600000$abc'],
  ['unknown algorithm', 'bcrypt$12$abc$def'],
  ['non-numeric iterations', 'pbkdf2_sha256$many$YWJj$ZGVm'],
  ['empty salt', 'pbkdf2_sha256$600000$$ZGVm'],
] as const
for (const [label, stored] of junk) {
  let threw = false
  let result = true
  try { result = await verifyPassword('anything', stored) } catch { threw = true }
  check(`${label} -> false, no throw`, !threw && result === false)
}

console.log('\n== a Node-generated hash round-trips ==')
const fresh = await hashPassword('correct horse battery staple')
check('format is pbkdf2_sha256$<iters>$<salt>$<digest>', fresh.split('$').length === 4)
check('iteration count is 600000', fresh.split('$')[1] === '600000')
check('verifies with the right password', await verifyPassword('correct horse battery staple', fresh))
check('rejects the wrong password', !(await verifyPassword('wrong', fresh)))

// Handed back to Python by the runner to close the loop.
console.log('\nNODE_HASH_FOR_PYTHON=' + fresh)

console.log(`\n${passed}/${passed + failed} passed`)
process.exit(failed === 0 ? 0 : 1)
