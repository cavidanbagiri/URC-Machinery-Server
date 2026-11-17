# repositories/car_status_lookup.py
"""Shared helpers for the operator-managed machine statuses (``car_statuses``).

The status rows are free text: the Settings page (``update_car_status``) lets an
admin rename them, and the labels are kept in Turkish — *Aktif*, *Bakımda*,
*Hurda*, *Arızalı*. The repair flow only needs to know which row means "this
machine is under repair", so names are normalised (Turkish/Azerbaijani letters
folded, case ignored) and compared against the known spellings instead of one
exact string. That keeps databases that still use the legacy seed value
("Tamirde") working next to ones renamed by hand ("Arızalı").
"""

from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import AllMachineModel, CarStatusModel

# Machine statuses that mean "the machine is under repair / faulty".
# Both the current Turkish label and the legacy seed value are accepted.
REPAIR_STATUS_ALIASES = frozenset(
    {
        "arizali",  # Arızalı  (current label)
        "tamirde",  # Tamirde  (legacy seed value)
        "tamirda",  # Azerbaijani spelling
        "temirde",  # Azerbaijani spelling folded (Təmirdə)
    }
)

# Seeded by migrations/d3e4f5a6b7c8_seed_car_statuses.py (id 2). Used as a last
# resort so a renamed row never blocks the repair flow with a hard 500.
REPAIR_STATUS_FALLBACK_ID = 2

REPAIR_STATUS_MISSING_DETAIL = (
    "Tamir (arıza) makine durumu bulunamadı. Ayarlar → Makine Durumu "
    "bölümünde \"Arızalı\" (veya \"Tamirde\") adlı bir durum tanımlayın."
)

_FOLD_MAP = {
    "ç": "c",
    "Ç": "c",
    "ğ": "g",
    "Ğ": "g",
    "ı": "i",
    "İ": "i",
    "I": "i",
    "ö": "o",
    "Ö": "o",
    "ş": "s",
    "Ş": "s",
    "ü": "u",
    "Ü": "u",
    "ə": "e",
    "Ə": "e",
}


def normalize_status_name(name: Optional[str]) -> str:
    """Fold a status name so "Arızalı", "ARIZALI" and "arizali " all match."""
    if not name:
        return ""

    folded = "".join(_FOLD_MAP.get(char, char) for char in str(name).strip())
    return " ".join(folded.casefold().split())


def is_repair_status_name(name: Optional[str]) -> bool:
    """True when the given label belongs to the "under repair" status."""
    return normalize_status_name(name) in REPAIR_STATUS_ALIASES


# =========================================================
# SCRAP ("Hurda") MACHINES
# =========================================================
# Machines whose status is "Hurda" must stay in the database (history, audit,
# spare part requests, ...) but they are retired equipment: they are filtered
# out of every list, counter and machine picker. The labels are editable in
# Settings, so the word "hurda" is matched instead of one exact seed value.
SCRAP_STATUS_KEYWORD = "hurda"


def is_scrap_status_name(name: Optional[str]) -> bool:
    """True when the given label belongs to the "scrapped" status."""
    return SCRAP_STATUS_KEYWORD in normalize_status_name(name)


def scrap_status_ids():
    """``SELECT car_statuses.id`` of the rows that mean "scrapped"."""
    return select(CarStatusModel.id).where(
        func.lower(func.trim(CarStatusModel.name)).like(f"%{SCRAP_STATUS_KEYWORD}%")
    )


def exclude_scrap_machines():
    """SQL condition that drops "Hurda" (scrapped) machines from a query.

    ``status_id IS NULL`` machines are kept: they simply have no status yet.
    """
    return or_(
        AllMachineModel.status_id.is_(None),
        ~AllMachineModel.status_id.in_(scrap_status_ids()),
    )


def pick_repair_status(
    statuses: Iterable[CarStatusModel],
) -> Optional[CarStatusModel]:
    """Return the "under repair" status from an already fetched list, if any."""
    ordered = list(statuses)
    for status in ordered:
        if is_repair_status_name(status.name):
            return status

    for status in ordered:
        if status.id == REPAIR_STATUS_FALLBACK_ID:
            return status

    return None


async def resolve_repair_status(db: AsyncSession) -> CarStatusModel:
    """Fetch the machine status that marks a machine as under repair.

    Raises ``HTTPException(409)`` with an actionable message when the table has
    neither a known label nor the seeded row, instead of a bare 500.
    """
    result = await db.execute(select(CarStatusModel).order_by(CarStatusModel.id))
    status = pick_repair_status(result.scalars().all())
    if status is None:
        raise HTTPException(status_code=409, detail=REPAIR_STATUS_MISSING_DETAIL)
    return status
