"""
Generate hashes with the live Python implementation for Node to verify.

Passwords are made up here. No real account's password or stored hash is read.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
os.environ.setdefault('DATABASE_URL', '')

from auth import hash_password, PBKDF2_ITERATIONS  # noqa: E402

CASES = [
    ('bowling123', 'ordinary password'),
    ('a' * 72, 'very long password'),
    ('pässwörd-ünïcode-🎳', 'non-ascii and emoji'),
    ('has$dollar$signs', 'dollar signs, which are the field separator'),
    ('   leading and trailing   ', 'whitespace is significant'),
]

out = {'iterations': PBKDF2_ITERATIONS,
       'cases': [{'password': p, 'hash': hash_password(p), 'note': n} for p, n in CASES]}

target = pathlib.Path(__file__).with_name('password-fixtures.json')
target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'wrote {len(CASES)} fixtures at {PBKDF2_ITERATIONS} iterations')
