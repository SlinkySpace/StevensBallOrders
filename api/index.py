"""
Vercel entrypoint.

Vercel's Python runtime turns each file under api/ into a serverless function
and looks for an ASGI application named `app`. vercel.json rewrites every path
here, so this one function serves the whole API rather than Vercel guessing a
route per file - which is what it did on the first deploy, publishing
api/sessions.py as an endpoint too.
"""

from api.main import app  # noqa: F401  (Vercel imports `app` from this module)
