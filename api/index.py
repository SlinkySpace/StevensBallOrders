"""
Vercel entrypoint.

Vercel detects FastAPI by importing this module and checking that `app` is a
FastAPI instance, then routes every request to it. So `app` must be a plain
top-level binding, and it must be a FastAPI instance on every path through this
file - including the failure path.

An earlier version fell back to a bare ASGI function when the import failed, to
report the reason instead of FUNCTION_INVOCATION_FAILED. That broke the
detection it was meant to support:

    Found api/index.py but it does not define a top-level "app" FastAPI instance

The fallback below is a real FastAPI app, so detection still succeeds, and a
deployment that cannot import its own code says why instead of returning an
opaque 500.
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from server import main as _main

    app = _main.app
except Exception as exc:  # pragma: no cover - only on a broken deployment
    import os

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    _error = f'{type(exc).__name__}: {exc}'
    _trace = traceback.format_exc()

    app = FastAPI(title='Bowling order API (failed to start)')

    @app.get('/{path:path}')
    def _startup_failure(path: str) -> JSONResponse:
        """Report why the real application could not be imported."""
        body = {
            'error': _error,
            'hint': 'The API failed to import. This is a deployment problem, '
                    'not a request problem.',
            'python': sys.version.split()[0],
            'root': str(ROOT),
            'root_py_files': sorted(p.name for p in ROOT.glob('*.py'))[:25],
            'server_dir_present': (ROOT / 'server').is_dir(),
            'server_files': sorted(p.name for p in (ROOT / 'server').glob('*.py'))
                            if (ROOT / 'server').is_dir() else [],
            'database_url_set': bool(os.environ.get('DATABASE_URL')),
            'session_secret_set': bool(os.environ.get('SESSION_SECRET')),
        }
        # Names file paths and nothing else, but only when asked for.
        if os.environ.get('DEBUG_STARTUP', '').lower() in {'1', 'true', 'yes'}:
            body['traceback'] = _trace
        return JSONResponse(body, status_code=500)
