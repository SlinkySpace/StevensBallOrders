/**
 * Password verification compatible with the Python app's auth.hash_password().
 *
 * Stored format, produced by hashlib.pbkdf2_hmac in auth.py:
 *
 *     pbkdf2_sha256$600000$<base64 salt>$<base64 digest>
 *
 * Every existing account's hash has to keep verifying, or the team is locked
 * out on the day of the cutover. So this reads the iteration count and salt
 * out of the stored string rather than assuming today's constants - an
 * account created before the count was raised still has the old number baked
 * into its own hash.
 */

import { pbkdf2, timingSafeEqual } from 'node:crypto'
import { promisify } from 'node:util'

const pbkdf2Async = promisify(pbkdf2)

export const PBKDF2_ALGORITHM = 'pbkdf2_sha256'
export const PBKDF2_ITERATIONS = 600_000
const SALT_BYTES = 16
const DIGEST_BYTES = 32 // sha256

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  if (!password || !stored) return false

  const parts = stored.split('$')
  if (parts.length !== 4) return false

  const [algorithm, iterations, saltB64, digestB64] = parts
  if (algorithm !== PBKDF2_ALGORITHM) return false

  const rounds = Number.parseInt(iterations, 10)
  if (!Number.isInteger(rounds) || rounds < 1) return false

  let salt: Buffer
  let expected: Buffer
  try {
    salt = Buffer.from(saltB64, 'base64')
    expected = Buffer.from(digestB64, 'base64')
  } catch {
    return false
  }
  if (salt.length === 0 || expected.length === 0) return false

  const candidate = await pbkdf2Async(
    Buffer.from(password, 'utf8'), salt, rounds, expected.length, 'sha256',
  )

  // Lengths must match before timingSafeEqual, which throws otherwise.
  if (candidate.length !== expected.length) return false
  return timingSafeEqual(candidate, expected)
}

/** Only for the compatibility test - the proof never writes a password. */
export async function hashPassword(password: string): Promise<string> {
  const { randomBytes } = await import('node:crypto')
  const salt = randomBytes(SALT_BYTES)
  const digest = await pbkdf2Async(
    Buffer.from(password, 'utf8'), salt, PBKDF2_ITERATIONS, DIGEST_BYTES, 'sha256',
  )
  return [
    PBKDF2_ALGORITHM,
    String(PBKDF2_ITERATIONS),
    salt.toString('base64'),
    digest.toString('base64'),
  ].join('$')
}
