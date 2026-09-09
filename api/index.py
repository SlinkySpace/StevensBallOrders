"""
Vercel entrypoint.

Vercel detects FastAPI by importing this module and checking that `app` is a
FastAPI instance, then routes every request to it. So `app` must be a plain
top-level binding to the real application and nothing else.

An earlier version wrapped the import in try/except and fell back to a small
ASGI function that reported why the import failed. That made failures readable
in principle, but `app` was then a function rather than a FastAPI instance, and
the build refused it:

    Found api/index.py but it does not define a top-level "app" FastAPI instance

The build log reports import errors on its own, so the fallback bought nothing
and cost the detection it was meant to support.

The repo root goes on sys.path here, before server.main is imported.
server/main.py sets it too, but that line cannot run until importing it has
already succeeded - and locally that only worked because the process happened
to start in the repo root.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import main as _main  # noqa: E402

# A literal top-level assignment, so the detector cannot miss it.
app = _main.app
