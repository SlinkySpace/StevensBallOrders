"""
Streamlit when it is there, plain Python when it is not.

db.py, auth.py, config.py and email_utils.py are shared by three callers now:
the Streamlit app, the scraper's sync, and the write API. Only the first of
those is running inside Streamlit, but all of them imported it - which is a
5-second import and about 100MB of wheels, and on a Vercel serverless function
it is simply not installed, so the function crashed on import.

Nothing here changes what the Streamlit app does: when Streamlit is importable
every call forwards to it. The fallbacks only apply off-Streamlit.
"""

import functools
import os

try:  # pragma: no cover - depends on where this is running
    import streamlit as _st
except ModuleNotFoundError:
    _st = None

RUNNING_UNDER_STREAMLIT = _st is not None


def cache_resource(**kwargs):
    """
    st.cache_resource under Streamlit, otherwise a plain process-wide cache.

    Both memoise one shared object per process, which is what the callers want
    it for - a connection pool. On serverless the process is short-lived, so the
    cache holds for one invocation and no longer, which is correct rather than
    unfortunate: a pooled connection cannot outlive the container anyway.
    """
    def decorate(func):
        if _st is not None:
            return _st.cache_resource(**kwargs)(func)
        cached = functools.lru_cache(maxsize=None)(func)
        # st.cache_resource spells it .clear(); lru_cache spells it
        # .cache_clear(). Callers use the Streamlit name, so expose it here too
        # rather than making every call site check which shim it got.
        cached.clear = cached.cache_clear
        return cached
    return decorate


def cache_data(**kwargs):
    """st.cache_data under Streamlit, otherwise no caching at all.

    Deliberately not lru_cache: cache_data memoises *values* that callers
    expect to go stale on a TTL, and a permanent cache off-Streamlit would
    serve a catalog that never refreshes.
    """
    def decorate(func):
        if _st is not None:
            return _st.cache_data(**kwargs)(func)
        # Nothing is cached off-Streamlit, so there is nothing to clear - but
        # invalidate_catalog_cache() still calls .clear() on the result, and a
        # bare function has no such attribute. Without this the CSV import
        # raises AttributeError anywhere Streamlit is absent, which is exactly
        # where the write API runs.
        func.clear = lambda: None
        return func
    return decorate


def secret(key: str, default=None):
    """
    Read from st.secrets, then the environment.

    st.secrets raises when there is no secrets.toml rather than returning a
    default, which used to crash a fresh clone on import.
    """
    if _st is not None:
        try:
            if key in _st.secrets:
                return _st.secrets[key]
        except Exception:
            pass
    return os.environ.get(key, default)


def toast(message: str) -> None:
    """A Streamlit toast where there is a UI; a no-op where there is not."""
    if _st is not None:
        _st.toast(message)


class _NoSessionState:
    """
    Stands in for st.session_state off-Streamlit, and refuses to work.

    A dict would be worse than an error here. Streamlit's session state is
    per-user; a module-level dict is per-process, and a warm serverless
    container serves many users from one process - so a silent fallback would
    hand one person's session to the next request. The write API keeps its own
    signed-cookie sessions and never touches this, and if that ever stops being
    true it should fail loudly.
    """

    def _refuse(self, *_args, **_kwargs):
        raise RuntimeError(
            'st.session_state is not available outside Streamlit. This code '
            'path is per-user state and must not run in a shared process - the '
            'write API uses signed cookies instead (api/sessions.py).'
        )

    __getattr__ = _refuse
    __getitem__ = _refuse
    __setitem__ = _refuse
    __contains__ = _refuse
    get = _refuse


class _SessionStateProxy:
    """
    Forwards to st.session_state on each access rather than at import.

    Reading st.session_state while merely importing a module - which is what
    sync_catalog.py and the tests do - warns that session state does not work
    outside `streamlit run`. Resolving it per access means that only happens
    when something actually uses it.
    """

    def __getattr__(self, name):
        return getattr(_st.session_state, name)

    def __getitem__(self, key):
        return _st.session_state[key]

    def __setitem__(self, key, value):
        _st.session_state[key] = value

    def __contains__(self, key):
        return key in _st.session_state

    def get(self, key, default=None):
        return _st.session_state.get(key, default)


session_state = _SessionStateProxy() if _st is not None else _NoSessionState()
