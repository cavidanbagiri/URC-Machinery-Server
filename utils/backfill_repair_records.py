# utils/backfill_repair_records.py
"""Open the missing repair records for machines that are marked as "Arızalı".

Usage (from the ``server`` directory, with the virtualenv active)::

    python -m utils.backfill_repair_records --dry-run
    python -m utils.backfill_repair_records

Some machines were switched to the repair status (the machine status that means
"under repair", ``Arızalı`` / the legacy ``Tamirde``) before the quick-open flow
started creating a repair record, so the machine list shows them as faulty while
the Repair page has no open record for them. This script lists those machines
and opens a repair for each through ``RepairRepository.quick_open_repair``: the
catch-all repair type (``Diğer``), today's entry date, no garage service and no
user (a system action), with the machine status left untouched because it is
already the repair status.

The script is idempotent — machines that already have an open repair are skipped
— so it is safe to run again. Use ``--dry-run`` to only print the list.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

from sqlalchemy import select

from database.setup import SessionLocal
from models.machines_model import AllMachineModel
from models.repair_model import RepairLogModel, RepairRecordModel, RepairTypeModel
from repositories.car_status_lookup import resolve_repair_status
from repositories.repair_repository import (
    QUICK_OPEN_REPAIR_TYPE_NAME,
    RepairRepository,
)

# Written to the repair notes (and log) so the record explains where it came from.
BACKFILL_NOTE = (
    "Kayıt, makine Arızalı durumunda iken açık tamir kaydı bulunmadığı için "
    "sistem tarafından oluşturuldu."
)


def _normalize_type_name(name: Optional[str]) -> str:
    if not name:
        return ""
    return " ".join(str(name).strip().casefold().split())


async def ensure_quick_open_type(
    session, dry_run: bool = False
) -> Optional[RepairTypeModel]:
    """Make sure the catch-all repair type used by quick-open exists.

    ``quick_open_repair`` prefers *Diğer* and silently falls back to the first
    repair type when it is missing, which would mislabel the record. Name
    comparison happens in Python so Turkish casing/collation cannot miss it.
    """
    result = await session.execute(select(RepairTypeModel).order_by(RepairTypeModel.id))
    wanted = _normalize_type_name(QUICK_OPEN_REPAIR_TYPE_NAME)
    for repair_type in result.scalars().all():
        if _normalize_type_name(repair_type.name) == wanted:
            return repair_type

    if dry_run:
        return None

    repair_type = RepairTypeModel(name=QUICK_OPEN_REPAIR_TYPE_NAME)
    session.add(repair_type)
    await session.commit()
    await session.refresh(repair_type)
    return repair_type


async def fetch_targets(session, repair_status_id: int) -> list[tuple[int, Optional[str]]]:
    """Return ``(machine_id, identification_no)`` of faulty machines without an open repair."""
    open_repairs = select(RepairRecordModel.machine_id).where(
        RepairRecordModel.status == "tamirde"
    )
    result = await session.execute(
        select(AllMachineModel.id, AllMachineModel.identification_no)
        .where(AllMachineModel.status_id == repair_status_id)
        .where(AllMachineModel.id.not_in(open_repairs))
        .order_by(AllMachineModel.id)
    )
    return [(row[0], row[1]) for row in result.all()]


async def backfill(dry_run: bool = False) -> int:
    async with SessionLocal() as session:
        repair_status = await resolve_repair_status(session)
        print(f"Repair status        : {repair_status.id} - {repair_status.name}")

        repair_type = await ensure_quick_open_type(session, dry_run=dry_run)
        if repair_type is None:
            print(f"Repair type          : would create '{QUICK_OPEN_REPAIR_TYPE_NAME}'")
        else:
            print(f"Repair type          : {repair_type.id} - {repair_type.name}")

        targets = await fetch_targets(session, repair_status.id)
        print(f"Machines to check    : {len(targets)}")
        if not targets:
            print("\nNothing to do: every faulty machine already has an open repair.")
            return 0

        repo = RepairRepository(session)
        created = 0
        for machine_id, identification_no in targets:
            label = identification_no or f"#{machine_id}"
            if dry_run:
                print(f"  would open repair for machine {machine_id} ({label})")
                continue

            item = await repo.quick_open_repair(machine_id, created_by_id=None)
            record = await session.get(RepairRecordModel, item["id"])
            if record is not None and not record.notes:
                record.notes = BACKFILL_NOTE
            session.add(
                RepairLogModel(
                    repair_id=item["id"],
                    event_type="note_added",
                    message=BACKFILL_NOTE,
                    created_by_id=None,
                )
            )
            await session.commit()

            created += 1
            print(
                f"  opened repair {item['id']} for machine {machine_id} ({label}), "
                f"entry_date={item['entry_date']}"
            )

        if dry_run:
            print("\nDry run: nothing was saved.")
            return 0

        print(f"\nRepairs created      : {created}")
        return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Open a repair record for every machine that is on the repair "
            "machine status but has no open repair record."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the machines that need a repair record.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(backfill(dry_run=args.dry_run))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
