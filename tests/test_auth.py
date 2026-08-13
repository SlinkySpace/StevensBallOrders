"""Auth tests, including migrating a database that predates the password column."""
import os, sys, sqlite3, tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
os.chdir(APP); sys.path.insert(0, APP)

import config
DB = Path(tempfile.gettempdir()) / "auth_test.db"
DB.unlink(missing_ok=True)
config.DB_PATH = DB
config.DATABASE_URL = ""
config.TEAM_ACCESS_CODE = ""

# Build a LEGACY database: the old users table, with no password_hash column.
legacy = sqlite3.connect(DB)
legacy.executescript("""
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL, last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE, saved_card TEXT DEFAULT '',
    balance_owed REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
INSERT INTO users(first_name,last_name,email,balance_owed,created_at)
    VALUES ('Jordan','Ela','jela@stevens.edu',120.0,'2026-03-30T22:00:00');
""")
legacy.commit(); legacy.close()

import db
db.DB_PATH = DB; db.USE_POSTGRES = False
import auth

results = []
def check(label, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"   {extra}" if extra and not cond else ""))

print("== migration on a pre-password database ==")
db.init_db()
cols = {r["name"] for r in sqlite3.connect(DB).execute("PRAGMA table_info(users)").fetchall() and
        [dict(zip([d[0] for d in c.description], c)) for c in []]} if False else None
conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
check("password_hash column added to existing table", "password_hash" in cols, str(cols))
row = conn.execute("SELECT * FROM users WHERE email='jela@stevens.edu'").fetchone()
check("existing user survived migration with balance intact", row and row["balance_owed"] == 120.0)
check("legacy account has empty password_hash", not (row["password_hash"] or "").strip())
conn.close()

print("\n== hashing ==")
h = auth.hash_password("correct horse battery")
check("hash has the expected format", h.startswith("pbkdf2_sha256$600000$") and h.count("$") == 3)
check("plaintext never appears in the hash", "correct horse battery" not in h)
check("verify accepts the right password", auth.verify_password("correct horse battery", h))
check("verify rejects a wrong password", not auth.verify_password("wrong", h))
check("verify rejects empty", not auth.verify_password("", h))
check("verify rejects garbage stored value", not auth.verify_password("x", "not-a-hash"))
check("verify rejects empty stored value", not auth.verify_password("x", ""))
check("two hashes of the same password differ (salted)",
      auth.hash_password("same") != auth.hash_password("same"))

print("\n== legacy account cannot log in without setting a password ==")
ok, err = auth.login_user("jela@stevens.edu", "")
check("empty password rejected", not ok)
ok, err = auth.login_user("jela@stevens.edu", "anything")
check("arbitrary password rejected for passwordless account", not ok, err)
check("account_needs_password() detects it", auth.account_needs_password("jela@stevens.edu"))

print("\n== first-time password setup ==")
auth._failed_logins.clear()
ok, err = auth.set_initial_password("jela@stevens.edu", "short", "short")
check("rejects a too-short password", not ok and "8 characters" in err, err)
ok, err = auth.set_initial_password("jela@stevens.edu", "goodpassword", "mismatch")
check("rejects mismatched confirmation", not ok and "match" in err, err)
ok, err = auth.set_initial_password("nobody@stevens.edu", "goodpassword", "goodpassword")
check("rejects unknown email", not ok, err)

import streamlit as st
ok, err = auth.set_initial_password("jela@stevens.edu", "goodpassword", "goodpassword")
check("accepts a valid password", ok, err)
check("balance preserved after claiming",
      float(db.get_user_by_email("jela@stevens.edu")["balance_owed"]) == 120.0)
check("account no longer needs a password", not auth.account_needs_password("jela@stevens.edu"))
ok, err = auth.set_initial_password("jela@stevens.edu", "anotherpass", "anotherpass")
check("cannot re-claim an account that has a password", not ok, err)

print("\n== login ==")
ok, err = auth.login_user("jela@stevens.edu", "goodpassword")
check("correct password logs in", ok, err)
check("session user has no password_hash",
      "password_hash" not in (st.session_state.get("user") or {}))
auth._failed_logins.clear()
ok, err = auth.login_user("jela@stevens.edu", "goodpasswor")
check("wrong password rejected", not ok)
ok2, err2 = auth.login_user("nobody@stevens.edu", "whatever")
check("unknown email gives the same message as a wrong password", err == err2, f"{err!r} vs {err2!r}")
auth._failed_logins.clear()
ok, err = auth.login_user("  JELA@Stevens.EDU  ", "goodpassword")
check("email is case/whitespace insensitive", ok, err)

print("\n== lockout ==")
auth._failed_logins.clear()
for _ in range(auth.MAX_FAILED_ATTEMPTS):
    auth.login_user("jela@stevens.edu", "nope")
ok, err = auth.login_user("jela@stevens.edu", "goodpassword")
check("locks out after repeated failures even with the right password", not ok, err)
check("lockout message reports remaining seconds", "seconds" in err, err)
check("lockout_seconds_remaining is positive", auth.lockout_seconds_remaining("jela@stevens.edu") > 0)
auth._failed_logins.clear()
ok, err = auth.login_user("jela@stevens.edu", "goodpassword")
check("login works again once the lockout clears", ok, err)

print("\n== change password ==")
ok, err = auth.change_password("jela@stevens.edu", "wrongcurrent", "brandnewpass", "brandnewpass")
check("rejects a wrong current password", not ok, err)
ok, err = auth.change_password("jela@stevens.edu", "goodpassword", "goodpassword", "goodpassword")
check("rejects reusing the current password", not ok, err)
ok, err = auth.change_password("jela@stevens.edu", "goodpassword", "short", "short")
check("rejects a weak new password", not ok, err)
ok, err = auth.change_password("jela@stevens.edu", "goodpassword", "brandnewpass", "brandnewpass")
check("accepts a valid change", ok, err)
auth._failed_logins.clear()
check("old password no longer works", not auth.login_user("jela@stevens.edu", "goodpassword")[0])
check("new password works", auth.login_user("jela@stevens.edu", "brandnewpass")[0])

print("\n== signup ==")
ok, err = auth.signup_user("A", "B", "new@stevens.edu", "validpassword", "validpassword")
check("creates a new account", ok, err)
ok, err = auth.signup_user("A", "B", "new@stevens.edu", "validpassword", "validpassword")
check("rejects a duplicate email", not ok, err)
ok, err = auth.signup_user("", "B", "x@stevens.edu", "validpassword", "validpassword")
check("rejects missing name", not ok, err)
ok, err = auth.signup_user("A", "B", "notanemail", "validpassword", "validpassword")
check("rejects a malformed email", not ok, err)
ok, err = auth.signup_user("A", "B", "y@stevens.edu", "short", "short")
check("rejects a weak password at signup", not ok, err)
stored = db.get_user_by_email("new@stevens.edu")["password_hash"]
check("signup stores a hash, not plaintext",
      stored.startswith("pbkdf2_sha256$") and "validpassword" not in stored)

print("\n== team access code ==")
config.TEAM_ACCESS_CODE = "letmein"
auth.TEAM_ACCESS_CODE = "letmein"
ok, err = auth.signup_user("C", "D", "coded@stevens.edu", "validpassword", "validpassword", "")
check("signup blocked without the code", not ok, err)
ok, err = auth.signup_user("C", "D", "coded@stevens.edu", "validpassword", "validpassword", "wrong")
check("signup blocked with a wrong code", not ok, err)
ok, err = auth.signup_user("C", "D", "coded@stevens.edu", "validpassword", "validpassword", "letmein")
check("signup allowed with the right code", ok, err)

db.create_user("Legacy", "User", "legacy@stevens.edu", "")
auth._failed_logins.clear()
ok, err = auth.set_initial_password("legacy@stevens.edu", "validpassword", "validpassword", "wrong")
check("claiming a legacy account blocked without the code", not ok, err)
auth._failed_logins.clear()
ok, err = auth.set_initial_password("legacy@stevens.edu", "validpassword", "validpassword", "letmein")
check("claiming allowed with the right code", ok, err)

print("\n== owner password reset ==")
uid = int(db.get_user_by_email("new@stevens.edu")["id"])
db.clear_user_password(uid)
check("reset clears the hash", auth.account_needs_password("new@stevens.edu"))
auth._failed_logins.clear()
check("old password stops working after reset",
      not auth.login_user("new@stevens.edu", "validpassword")[0])
ok, err = auth.set_initial_password("new@stevens.edu", "freshpassword", "freshpassword", "letmein")
check("user can set a new password after reset", ok, err)

DB.unlink(missing_ok=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
