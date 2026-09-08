import { getPasswordHashShapes } from '@/lib/db'
import { PBKDF2_ALGORITHM, PBKDF2_ITERATIONS } from '@/lib/password'

export const dynamic = 'force-dynamic'

/**
 * Deliberately not a login form. Proving people can still sign in does not
 * require anyone to type a password into an unfinished app - it requires
 * showing that every stored hash is one the Node verifier can read.
 */
export default async function SignInReadinessPage() {
  const shapes = await getPasswordHashShapes()

  const withPassword = shapes.filter((s) => s.hasPassword)
  const withoutPassword = shapes.filter((s) => !s.hasPassword)

  const compatible = withPassword.filter(
    (s) => s.algorithm === PBKDF2_ALGORITHM && s.iterations > 0 && s.saltBytes > 0 && s.digestBytes === 32,
  )
  const incompatible = withPassword.filter((s) => !compatible.includes(s))
  const iterationCounts = [...new Set(withPassword.map((s) => s.iterations))].sort((a, b) => a - b)
  const allGood = incompatible.length === 0

  return (
    <>
      <div className="page-head">Sign-in readiness</div>
      <div className="page-sub">Can every existing account still log in after a port?</div>

      <div className="banner">
        No login form on purpose. This reads the <em>shape</em> of each stored hash —
        never a hash, an email or a password — and checks the Node verifier can read it.
      </div>

      <div className="summary-row">
        <div>
          <div className="summary-label">Accounts</div>
          <div className="summary-value">{shapes.length}</div>
        </div>
        <div>
          <div className="summary-label">With a password</div>
          <div className="summary-value">{withPassword.length}</div>
        </div>
        <div>
          <div className="summary-label">Verifiable in Node</div>
          <div className={`summary-value ${allGood ? 'summary-value--accent' : ''}`}>
            {compatible.length}/{withPassword.length}
          </div>
        </div>
      </div>

      <table className="items">
        <thead>
          <tr><th>Check</th><th>Expected</th><th>Found</th><th>Result</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Algorithm</td>
            <td>{PBKDF2_ALGORITHM}</td>
            <td>{[...new Set(withPassword.map((s) => s.algorithm))].join(', ') || '—'}</td>
            <td>{withPassword.every((s) => s.algorithm === PBKDF2_ALGORITHM) ? 'PASS' : 'FAIL'}</td>
          </tr>
          <tr>
            <td>Iteration counts</td>
            <td>read from each hash (today {PBKDF2_ITERATIONS.toLocaleString()})</td>
            <td>{iterationCounts.map((n) => n.toLocaleString()).join(', ') || '—'}</td>
            <td>{withPassword.every((s) => s.iterations > 0) ? 'PASS' : 'FAIL'}</td>
          </tr>
          <tr>
            <td>Digest length</td>
            <td>32 bytes (sha256)</td>
            <td>{[...new Set(withPassword.map((s) => s.digestBytes))].join(', ') || '—'}</td>
            <td>{withPassword.every((s) => s.digestBytes === 32) ? 'PASS' : 'FAIL'}</td>
          </tr>
          <tr>
            <td>Salt length</td>
            <td>non-empty</td>
            <td>{[...new Set(withPassword.map((s) => s.saltBytes))].join(', ') || '—'} bytes</td>
            <td>{withPassword.every((s) => s.saltBytes > 0) ? 'PASS' : 'FAIL'}</td>
          </tr>
        </tbody>
      </table>

      <p className="page-sub" style={{ marginTop: '1.5rem' }}>
        {allGood
          ? `All ${withPassword.length} accounts with a password would verify unchanged — no resets needed.`
          : `${incompatible.length} account(s) would NOT verify. Investigate before any cutover.`}
        {withoutPassword.length > 0 && ` ${withoutPassword.length} account(s) have never set a password
           and would use the same "first time here?" flow they use today.`}
      </p>
    </>
  )
}
