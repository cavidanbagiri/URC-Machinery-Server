# repositories/fuel_log_window.py
"""Shared date window of the **Kayıtları düzenle** dialog.

Both diesel ledgers (``machine_fuel_logs`` and ``machine_rental_fuel_logs``)
expose their recent rows so a wrong entry can be corrected later.  The window
is resolved in one place, so the machine tab and the Kiralık tab always list
the same number of days and never reach into the future.
"""

from datetime import date, timedelta
from typing import Optional, Tuple

#: How many days back the correction dialog lists by default.  The selected day
#: is the inclusive upper bound, so the dialog covers "this day and the 29 days
#: before it".
DEFAULT_EDIT_WINDOW_DAYS = 30

#: Hard limit of ``days``; a full year is more than any correction needs.
MAX_EDIT_WINDOW_DAYS = 366


def resolve_edit_window(
    target_date: Optional[date] = None,
    days: int = DEFAULT_EDIT_WINDOW_DAYS,
) -> Tuple[date, date]:
    """Return the inclusive ``(start_date, end_date)`` of the row list.

    ``target_date`` is the day selected on the page and is clamped to today, so
    a future date can never widen the window.  ``days`` is clamped to
    :data:`DEFAULT_EDIT_WINDOW_DAYS`-style bounds instead of raising, because it
    only shapes a list - the endpoints still validate the query parameter.
    """

    today = date.today()
    end = min(target_date or today, today)

    span = DEFAULT_EDIT_WINDOW_DAYS if days is None else int(days)
    span = max(1, min(span, MAX_EDIT_WINDOW_DAYS))

    return end - timedelta(days=span - 1), end


__all__ = [
    "DEFAULT_EDIT_WINDOW_DAYS",
    "MAX_EDIT_WINDOW_DAYS",
    "resolve_edit_window",
]
