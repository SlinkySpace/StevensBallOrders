"""
Run every self-contained test in this directory.

    python tests/run_all.py

Each test is a standalone script that exits non-zero on failure, prints its own
PASS/FAIL lines, and builds whatever state it needs in a throwaway SQLite file
under the system temp directory. None of them touch the hosted database.

Tests under tests/manual/ are not run here - they need an argument or the live
stormbowling.com site. See tests/README.md.
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent


def main() -> int:
    scripts = sorted(TESTS_DIR.glob('test_*.py'))
    if not scripts:
        print('No tests found.', file=sys.stderr)
        return 1

    width = max(len(s.stem) for s in scripts)
    failures = []

    for script in scripts:
        print(f'{script.stem:<{width}}  ', end='', flush=True)
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=REPO, capture_output=True, text=True,
        )
        # Every test ends with its own summary line; show that rather than the
        # whole transcript, which runs to hundreds of lines across the suite.
        tail = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        summary = tail[-1].strip() if tail else '(no output)'

        if result.returncode == 0:
            print(summary)
        else:
            print(f'FAILED - {summary}')
            failures.append((script.stem, result))

    print()
    if not failures:
        print(f'All {len(scripts)} test files passed.')
        return 0

    for name, result in failures:
        print(f'\n{"=" * 70}\n{name} (exit {result.returncode})\n{"=" * 70}')
        print(result.stdout[-4000:])
        if result.stderr.strip():
            print('--- stderr ---')
            print(result.stderr[-2000:])

    print(f'\n{len(failures)} of {len(scripts)} test files failed.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
