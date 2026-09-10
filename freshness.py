"""
How old the catalog is, in words.

Lifted out of the Streamlit Catalog Manager, which is not coming across. The
logic is pure Python - no pandas, no UI - and the question it answers ("when
did Storm's prices last land?") matters more in a web app than it did there,
because nobody is watching a sidebar for it.
"""

from datetime import datetime

# Past this, the catalog is old enough that prices are worth doubting. Storm's
# session cookies expire within the hour, so a refresh needs someone present;
# a month without one usually means nobody has run it since term started.
STALE_CATALOG_DAYS = 30


def humanize_age(timestamp: str) -> tuple[str, int]:
    """Return a friendly age like '3 days ago', plus the age in days."""
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except (TypeError, ValueError):
        # Unparseable reads as impossibly old rather than brand new, so a
        # broken timestamp shows a warning instead of hiding one.
        return 'unknown', 10**6

    delta = datetime.now() - moment
    days = max(delta.days, 0)
    if days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            return 'just now', 0
        return f'{hours} hour{"s" if hours != 1 else ""} ago', 0
    if days == 1:
        return 'yesterday', 1
    if days < 30:
        return f'{days} days ago', days
    months = days // 30
    return f'about {months} month{"s" if months != 1 else ""} ago', days


def is_stale(days: int) -> bool:
    return days >= STALE_CATALOG_DAYS
