# repositories/isg_repository.py
"""Data access for the ISG (occupational safety) nonconformity page.

One row per nonconformity.  Paging, searching and every filter stay in SQL; the
status/severity labels, the site name and the evidence metadata are shaped while
the rows are mapped, so the list endpoint answers in one round trip.

The stat cards (SRU/DCU opened + closed) are a single ``GROUP BY`` query and
:func:`summarize_overview` — the helper is pure, which keeps the SRU/DCU rule
(testable offline) in one place: the site name is compared trimmed and
case-insensitively, so " sru " counts as SRU.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.isg_model import (
    ISG_SEVERITIES,
    ISG_SEVERITY_LABELS,
    ISG_STAT_SITES,
    ISG_STATUSES,
    ISG_STATUS_CLOSED,
    ISG_STATUS_LABELS,
    ISG_STATUS_OPEN,
    IsgAttachmentModel,
    IsgNonconformityModel,
)
from models.machines_model import TerritoryModel
from models.user_model import UserModel
from repositories.isg_evidence import is_image_content_type, validate_evidence
from schemas.isg_schemas import IsgNonconformityWriteSchema

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

NOT_FOUND_DETAIL = "ISG kaydı bulunamadı"
ATTACHMENT_NOT_FOUND_DETAIL = "Kanıt bulunamadı"


def summarize_overview(rows) -> dict[str, int]:
    """Turn ``(territory_name, status, count)`` rows into the card numbers."""

    sites = {
        site: {"opened": 0, "open": 0, "closed": 0} for site in ISG_STAT_SITES
    }
    total = 0
    open_total = 0
    closed_total = 0

    for territory_name, status, count in rows:
        amount = int(count or 0)
        total += amount

        is_closed = status == ISG_STATUS_CLOSED
        if is_closed:
            closed_total += amount
        else:
            open_total += amount

        site = (territory_name or "").strip().upper()
        if site not in sites:
            continue

        sites[site]["opened"] += amount
        sites[site]["closed" if is_closed else "open"] += amount

    return {
        "total": total,
        "open_total": open_total,
        "closed_total": closed_total,
        "sru_opened": sites["SRU"]["opened"],
        "sru_open": sites["SRU"]["open"],
        "sru_closed": sites["SRU"]["closed"],
        "dcu_opened": sites["DCU"]["opened"],
        "dcu_open": sites["DCU"]["open"],
        "dcu_closed": sites["DCU"]["closed"],
        "sites_closed_total": sites["SRU"]["closed"] + sites["DCU"]["closed"],
    }


def summarize_projects(rows) -> dict[str, Any]:
    """Turn ``(territory_id, territory_name, status, count)`` rows into one
    line per project (site) for the dashboard summary table.

    Unlike :func:`summarize_overview`, no site is special-cased: every project
    that owns at least one record appears, so a new site in Ayarlar shows up
    without a code change.  The busiest project (most open records) comes
    first, then the larger one; the name breaks ties alphabetically.
    """

    projects: dict[int, dict[str, Any]] = {}
    open_total = 0
    closed_total = 0

    for territory_id, territory_name, status, count in rows:
        amount = int(count or 0)
        is_closed = status == ISG_STATUS_CLOSED

        if is_closed:
            closed_total += amount
        else:
            open_total += amount

        entry = projects.get(territory_id)
        if entry is None:
            entry = {
                "territory_id": territory_id,
                "territory_name": (territory_name or "").strip() or "—",
                "open": 0,
                "closed": 0,
                "total": 0,
            }
            projects[territory_id] = entry

        entry["closed" if is_closed else "open"] += amount
        entry["total"] += amount

    items = sorted(
        projects.values(),
        key=lambda item: (
            -item["open"],
            -item["total"],
            item["territory_name"].casefold(),
        ),
    )

    return {
        "project_count": len(items),
        "total": open_total + closed_total,
        "open_total": open_total,
        "closed_total": closed_total,
        "items": items,
    }


def joined_names(firstname: Optional[str], lastname: Optional[str]) -> Optional[str]:
    """``"Ayşe Yılmaz"`` (or ``None``) — the creator / closer line of a row."""

    name = " ".join(part for part in (firstname, lastname) if part).strip()
    return name or None


class IsgRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================
    # SELECT / MAPPING
    # =========================================================

    def _base_select(self):
        creator = aliased(UserModel)
        closer = aliased(UserModel)

        return (
            select(
                IsgNonconformityModel,
                TerritoryModel.name.label("territory_name"),
                creator.firstname.label("creator_firstname"),
                creator.lastname.label("creator_lastname"),
                closer.firstname.label("closer_firstname"),
                closer.lastname.label("closer_lastname"),
            )
            .select_from(IsgNonconformityModel)
            .join(
                TerritoryModel,
                IsgNonconformityModel.territory_id == TerritoryModel.id,
            )
            .outerjoin(
                creator,
                IsgNonconformityModel.created_by_id == creator.id,
            )
            .outerjoin(
                closer,
                IsgNonconformityModel.closed_by_id == closer.id,
            )
        )

    async def _attachments_for(self, item_ids: list[int]) -> dict[int, list[dict]]:
        """Evidence metadata (never the bytes) grouped by nonconformity id."""

        if not item_ids:
            return {}

        result = await self.db.execute(
            select(
                IsgAttachmentModel.id,
                IsgAttachmentModel.nonconformity_id,
                IsgAttachmentModel.file_name,
                IsgAttachmentModel.content_type,
                IsgAttachmentModel.file_size,
                IsgAttachmentModel.uploaded_by_id,
                IsgAttachmentModel.created_at,
            )
            .where(IsgAttachmentModel.nonconformity_id.in_(item_ids))
            .order_by(IsgAttachmentModel.id)
        )

        grouped: dict[int, list[dict]] = {}
        for row in result.all():
            grouped.setdefault(row.nonconformity_id, []).append(
                {
                    "id": row.id,
                    "file_name": row.file_name,
                    "content_type": row.content_type,
                    "file_size": row.file_size,
                    "is_image": is_image_content_type(row.content_type),
                    "uploaded_by_id": row.uploaded_by_id,
                    "created_at": row.created_at,
                }
            )
        return grouped

    def _row_to_item(self, row, attachments: list[dict]) -> dict[str, Any]:
        record: IsgNonconformityModel = row[0]

        return {
            "id": record.id,
            "record_date": record.record_date,
            "description": record.description,
            "status": record.status,
            "status_label": ISG_STATUS_LABELS.get(record.status, record.status),
            "severity": record.severity,
            "severity_label": ISG_SEVERITY_LABELS.get(
                record.severity, record.severity
            ),
            "territory_id": record.territory_id,
            "territory_name": row.territory_name,
            "responsible_name": record.responsible_name,
            "closed_at": record.closed_at,
            "closed_by_id": record.closed_by_id,
            "closed_by_name": joined_names(
                row.closer_firstname, row.closer_lastname
            ),
            "created_by_id": record.created_by_id,
            "created_by_name": joined_names(
                row.creator_firstname, row.creator_lastname
            ),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "attachment_count": len(attachments),
            "attachments": attachments,
        }

    def _filters(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        territory_id: Optional[int] = None,
        responsible_name: Optional[str] = None,
        date_from=None,
        date_to=None,
    ) -> list:
        filters: list = []

        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                or_(
                    IsgNonconformityModel.description.ilike(pattern),
                    IsgNonconformityModel.responsible_name.ilike(pattern),
                    TerritoryModel.name.ilike(pattern),
                )
            )

        if status:
            if status not in ISG_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="Geçersiz durum filtresi",
                )
            filters.append(IsgNonconformityModel.status == status)

        if severity:
            if severity not in ISG_SEVERITIES:
                raise HTTPException(
                    status_code=400,
                    detail="Geçersiz önem derecesi filtresi",
                )
            filters.append(IsgNonconformityModel.severity == severity)

        if territory_id is not None:
            filters.append(IsgNonconformityModel.territory_id == territory_id)

        responsible = (responsible_name or "").strip()
        if responsible:
            filters.append(
                func.lower(IsgNonconformityModel.responsible_name)
                == responsible.lower()
            )

        if date_from is not None:
            filters.append(IsgNonconformityModel.record_date >= date_from)
        if date_to is not None:
            filters.append(IsgNonconformityModel.record_date <= date_to)

        return filters

    def _count_select(self, filters: list):
        # The search filter may reference the site name, so the join is always
        # part of the count query (one row per nonconformity, never duplicated).
        return (
            select(func.count(IsgNonconformityModel.id))
            .select_from(IsgNonconformityModel)
            .join(
                TerritoryModel,
                IsgNonconformityModel.territory_id == TerritoryModel.id,
            )
            .where(*filters)
        )

    async def _fetch_item(self, item_id: int) -> dict[str, Any]:
        row = (
            await self.db.execute(
                self._base_select().where(IsgNonconformityModel.id == item_id)
            )
        ).first()

        if row is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)

        attachments = await self._attachments_for([item_id])
        return self._row_to_item(row, attachments.get(item_id, []))

    async def _get_orm(self, item_id: int) -> IsgNonconformityModel:
        record = await self.db.get(IsgNonconformityModel, item_id)
        if record is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
        return record

    async def _ensure_territory(self, territory_id: int) -> None:
        if await self.db.get(TerritoryModel, territory_id) is None:
            raise HTTPException(
                status_code=400,
                detail="Seçilen şantiye bulunamadı",
            )

    @staticmethod
    def _apply_status(
        record: IsgNonconformityModel,
        status: str,
        user_id: Optional[int],
    ) -> None:
        """Keep ``status`` and the close stamp in sync (idempotent)."""

        if status not in ISG_STATUSES:
            raise HTTPException(status_code=400, detail="Geçersiz durum")

        if status == record.status:
            return

        if status == ISG_STATUS_CLOSED:
            record.closed_at = datetime.now(timezone.utc)
            record.closed_by_id = user_id
        else:
            record.closed_at = None
            record.closed_by_id = None

        record.status = status

    # =========================================================
    # LIST / STATS
    # =========================================================

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        territory_id: Optional[int] = None,
        responsible_name: Optional[str] = None,
        date_from=None,
        date_to=None,
    ) -> dict[str, Any]:
        if limit < 1:
            limit = DEFAULT_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        if offset < 0:
            offset = 0

        filters = self._filters(
            search=search,
            status=status,
            severity=severity,
            territory_id=territory_id,
            responsible_name=responsible_name,
            date_from=date_from,
            date_to=date_to,
        )

        total = (await self.db.scalar(self._count_select(filters))) or 0

        result = await self.db.execute(
            self._base_select()
            .where(*filters)
            .order_by(
                IsgNonconformityModel.record_date.desc(),
                IsgNonconformityModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = result.all()

        attachments = await self._attachments_for([row[0].id for row in rows])

        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": [
                self._row_to_item(row, attachments.get(row[0].id, []))
                for row in rows
            ],
        }

    async def fetch_overview(self) -> dict[str, int]:
        result = await self.db.execute(
            select(
                TerritoryModel.name,
                IsgNonconformityModel.status,
                func.count(IsgNonconformityModel.id),
            )
            .select_from(IsgNonconformityModel)
            .join(
                TerritoryModel,
                IsgNonconformityModel.territory_id == TerritoryModel.id,
            )
            .group_by(TerritoryModel.name, IsgNonconformityModel.status)
        )
        return summarize_overview(result.all())

    async def fetch_project_summary(self) -> dict[str, Any]:
        """Open/closed counts per project (site) — the dashboard table."""

        result = await self.db.execute(
            select(
                TerritoryModel.id,
                TerritoryModel.name,
                IsgNonconformityModel.status,
                func.count(IsgNonconformityModel.id),
            )
            .select_from(IsgNonconformityModel)
            .join(
                TerritoryModel,
                IsgNonconformityModel.territory_id == TerritoryModel.id,
            )
            .group_by(
                TerritoryModel.id,
                TerritoryModel.name,
                IsgNonconformityModel.status,
            )
        )
        return summarize_projects(result.all())

    # =========================================================
    # WRITE
    # =========================================================

    async def create(
        self,
        data: IsgNonconformityWriteSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        await self._ensure_territory(data.territory_id)

        record = IsgNonconformityModel(
            record_date=data.record_date,
            description=data.description,
            # Start open, then let _apply_status stamp closed_at/closed_by_id
            # when the form already saved the row as "Kapalı".
            status=ISG_STATUS_OPEN,
            severity=data.severity,
            territory_id=data.territory_id,
            responsible_name=data.responsible_name,
            created_by_id=user_id,
        )
        self._apply_status(record, data.status, user_id)

        self.db.add(record)

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "ISG kaydı kaydedilemedi; bilgileri kontrol edip "
                    "tekrar deneyin"
                ),
            ) from exc

        return await self._fetch_item(record.id)

    async def update(
        self,
        item_id: int,
        data: IsgNonconformityWriteSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_orm(item_id)
        await self._ensure_territory(data.territory_id)

        record.record_date = data.record_date
        record.description = data.description
        record.severity = data.severity
        record.territory_id = data.territory_id
        record.responsible_name = data.responsible_name
        self._apply_status(record, data.status, user_id)

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "ISG kaydı güncellenemedi; bilgileri kontrol edip "
                    "tekrar deneyin"
                ),
            ) from exc

        return await self._fetch_item(item_id)

    async def set_status(
        self,
        item_id: int,
        status: str,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        """The table's status dropdown (Açık <-> Kapalı)."""

        record = await self._get_orm(item_id)
        self._apply_status(record, status, user_id)

        await self.db.commit()
        return await self._fetch_item(item_id)

    async def delete(self, item_id: int) -> None:
        record = await self._get_orm(item_id)
        await self.db.delete(record)
        await self.db.commit()

    # =========================================================
    # EVIDENCE (PDF / photo)
    # =========================================================

    async def add_attachment(
        self,
        item_id: int,
        *,
        file_name: Optional[str],
        content_type: Optional[str],
        data: bytes,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        record = await self._get_orm(item_id)

        try:
            validated = validate_evidence(file_name, content_type, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        attachment = IsgAttachmentModel(
            nonconformity_id=record.id,
            file_data=data,
            uploaded_by_id=user_id,
            **validated,
        )
        self.db.add(attachment)
        await self.db.commit()

        return await self._fetch_item(item_id)

    async def get_attachment(
        self,
        item_id: int,
        attachment_id: int,
    ) -> IsgAttachmentModel:
        attachment = await self.db.get(IsgAttachmentModel, attachment_id)
        if attachment is None or attachment.nonconformity_id != item_id:
            raise HTTPException(
                status_code=404,
                detail=ATTACHMENT_NOT_FOUND_DETAIL,
            )
        return attachment

    async def delete_attachment(
        self,
        item_id: int,
        attachment_id: int,
    ) -> dict[str, Any]:
        attachment = await self.get_attachment(item_id, attachment_id)
        await self.db.delete(attachment)
        await self.db.commit()

        return await self._fetch_item(item_id)


__all__ = [
    "ATTACHMENT_NOT_FOUND_DETAIL",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "NOT_FOUND_DETAIL",
    "IsgRepository",
    "joined_names",
    "summarize_overview",
    "summarize_projects",
]
