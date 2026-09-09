"""
Vercel entrypoint.

Vercel's Python runtime turns a file under api/ into a serverless function and
looks for an ASGI application named `app`. vercel.json rewrites every path here,
so this one function serves the whole API rather than Vercel publishing a route
per file - which is what it did on the first deploy, exposing api/sessions.py as
an endpoint.

The repo root goes on sys.path *here*, before anything imports `api.main`.
api/main.py sets it too, but that line cannot run until the import of api.main
has already succeeded, and locally that import only worked because the process
happened to start in the repo root.
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api.main import app  # noqa: F401  (Vercel imports `app` from here)
except Exception as exc:  # pragma: no cover - only on a broken deployment
    # A serverless function that fails to import returns
    # FUNCTION_INVOCATION_FAILED and nothing else, which says the same thing
    # whether a dependency is missing, a path is wrong or the database is
    # unreachable. This deployment has already burned two rounds on that. So
    # serve the reason instead of dying.
    _error = f'{type(exc).__name__}: {exc}'
    _trace = traceback.format_exc()
    _detail = {
        'error': _error,
        'hint': 'The API failed to import. This is a deployment problem, not a request problem.',
        'python': sys.version.split()[0],
        'root_on_path': str(ROOT),
        'root_files': sorted(p.name for p in ROOT.glob('*.py'))[:20],
    }

    async def app(scope, receive, send):  # type: ignore[misc]
        """Minimal ASGI app that reports why the real one could not load."""
        if scope['type'] != 'http':
            return

        import json
        import os

        body = dict(_detail)
        # The traceback names file paths and nothing else, but it is only
        # served when explicitly asked for.
        if os.environ.get('DEBUG_STARTUP', '').lower() in {'1', 'true', 'yes'}:
            body['traceback'] = _trace

        payload = json.dumps(body, indent=2).encode('utf-8')
        await send({
            'type': 'http.response.start',
            'status': 500,
            'headers': [(b'content-type', b'application/json')],
        })
        await send({'type': 'http.response.body', 'body': payload})
