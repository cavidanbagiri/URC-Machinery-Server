# repositories/machine_kind_lookup.py
"""Shared helpers for machine kinds that are **not** maintenance machines.

A TIR trailer ("Tır Dorse") is towed equipment, not a machine: it has no engine
hour / kilometre counter of its own, so the **Bakım** page — the one that shows
the "Güncel KM / Saat" column and builds the maintenance summary cards — must
not list it. Trailers stay in ``all_machines``; faults, tires, documents and the
machine lists keep using them.

Two independent markers identify a trailer, so a renamed type or a corrected
code never leaves one behind:

* the type label contains "Dorse" — ``type_transports`` rows are editable in
  Settings, so the keyword is matched instead of one exact seed value
  ("Tır Dorse", "Tir Dorse", "Dorse" ...),
* the identification number starts with "TD" followed by a digit
  ("TD-101", "td 102", "TD103"), which is how the trailers are coded in the
  yard.

The frontend mirrors the type-keyword rule (``utils/maintenance.js``) to hide
the trailer type from the Bakım type filter.
"""

import re
from typing import Optional

from sqlalchemy import func, or_

from models.machines_model import AllMachineModel, TypeTransportModel

TRAILER_TYPE_KEYWORD = "dorse"

# "TD-101", "TD103", "TD 104" — but not "TDR-5".
TRAILER_IDENTIFICATION_PATTERN = r"^TD[- ]?[0-9]"

_TRAILER_IDENTIFICATION_RE = re.compile(
    TRAILER_IDENTIFICATION_PATTERN, re.IGNORECASE
)


def normalize_machine_label(value: Optional[str]) -> str:
    """Fold a type name / machine code so spacing and case stop mattering."""
    if not value:
        return ""

    return " ".join(str(value).strip().casefold().split())


def is_trailer_type_name(name: Optional[str]) -> bool:
    """True when a ``type_transports.name`` label means "TIR trailer"."""
    return TRAILER_TYPE_KEYWORD in normalize_machine_label(name)


def is_trailer_identification_no(value: Optional[str]) -> bool:
    """True when a machine code such as "TD-101" belongs to a trailer."""
    if not value:
        return False

    return _TRAILER_IDENTIFICATION_RE.match(str(value).strip()) is not None


def trailer_machine_condition():
    """SQL condition that is true for a TIR trailer row of ``all_machines``.

    ``type_id`` / ``identification_no`` are nullable, so the conditions are
    wrapped in ``COALESCE(..., false)``: a machine without a type or a code
    stays a machine.
    """

    type_label = func.lower(func.trim(TypeTransportModel.name))
    identification_no = func.upper(func.trim(AllMachineModel.identification_no))

    return or_(
        func.coalesce(
            type_label.like(f"%{TRAILER_TYPE_KEYWORD}%"),
            False,
        ),
        func.coalesce(
            identification_no.op("~")(TRAILER_IDENTIFICATION_PATTERN),
            False,
        ),
    )


def exclude_trailer_machines():
    """SQL condition that drops the TIR trailers from a query.

    Used by the Bakım list and its summary counters; expects
    ``TypeTransportModel`` to be joined (``maintenance_repository._base_select``
    already outer joins it).
    """

    return ~trailer_machine_condition()
