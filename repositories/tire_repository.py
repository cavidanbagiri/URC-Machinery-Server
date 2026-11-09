# repositories/tire_repository.py
"""Database access for tire changes (lastik değişimi) and their PDF papers."""

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    CarStatusModel,
)
from models.tire_model import (
    MAX_TIRE_DOCUMENT_BYTES,
    TireChangeDocumentModel,
    TireChangeModel,
)
from models.user_model import UserModel
from repositories.pdf_documents import (
    clamp_pagination,
    content_disposition,
    sanitize_file_name,
    validate_document,
)
from schemas.tire_schemas import TireChangeCreateSchema, normalize_position

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_MACHINE_OPTIONS = 50
#: How many older records the history endpoint returns for one position.
MAX_HISTORY = 20

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_HISTORY",
    "MAX_LIMIT",
    "MAX_MACHINE_OPTIONS",
    "MAX_TIRE_DOCUMENT_BYTES",
    "TireRepository",
    "clamp_pagination",
    "content_disposition",
    "position_matches",
    "sanitize_file_name",
    "validate_document",
]


# =========================================================
# PURE HELPERS
# =========================================================

def position_matches(column, position: str):
    """Case-insensitive comparison of a stored tire position.

    The position is free text, so one operator writes "Sol Ön" and another
    "sol ön"; both must belong to the same physical tire.
    """

    return func.lower(column) == " ".join((position or "").split()).lower()


# =========================================================
# REPOSITORY
# =========================================================

class TireRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    def _previous_count_column(self):
        """Correlated count of older changes of the same machine + position."""

        previous = aliased(TireChangeModel)
        return (
            select(func.count(previous.id))
            .where(
                previous.machine_id == TireChangeModel.machine_id,
                func.lower(previous.position)
                == func.lower(TireChangeModel.position),
                or_(
                    previous.change_date < TireChangeModel.change_date,
                    and_(
                        previous.change_date == TireChangeModel.change_date,
                        previous.id < TireChangeModel.id,
                    ),
                ),
            )
            .correlate(TireChangeModel)
            .scalar_subquery()
            .label("previous_count")
        )

    def _base_select(self):
        return (
            select(
                TireChangeModel,
                AllMachineModel,
                CarStatusModel.name.label("machine_status_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
                self._previous_count_column(),
            )
            .select_from(TireChangeModel)
            .join(AllMachineModel, TireChangeModel.machine_id == AllMachineModel.id)
            .outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)
            .outerjoin(CarMarkModel, AllMachineModel.car_mark_id == CarMarkModel.id)
            .outerjoin(CarModelModel, AllMachineModel.car_model_id == CarModelModel.id)
            .outerjoin(UserModel, TireChangeModel.created_by_id == UserModel.id)
        )

    def _row_to_item(self, row, documents: Optional[list[dict[str, Any]]] = None):
        change: TireChangeModel = row[0]
        machine: AllMachineModel = row[1]
        creator_name = " ".join(
            part for part in (row.creator_firstname, row.creator_lastname) if part
        ).strip()

        return {
            "id": change.id,
            "machine_id": machine.id,
            "identification_no": machine.identification_no,
            "plate_no": machine.plate_no,
            "vin_no": machine.vin_no,
            "car_mark_name": row.car_mark_name,
            "car_model_name": row.car_model_name,
            "machine_status_name": row.machine_status_name,
            "position": change.position,
            "brand_model": change.brand_model,
            "size": change.size,
            "change_reason": change.change_reason,
            "change_date": change.change_date,
            "km_hour": change.km_hour,
            "previous_count": row._mapping.get("previous_count") or 0,
            "created_by_id": change.created_by_id,
            "created_by_name": creator_name or None,
            "created_at": change.created_at,
            "updated_at": change.updated_at,
            "documents": documents or [],
        }

    async def _documents_for(
        self, tire_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Document metadata only: the PDF bytes never enter the list query."""

        grouped: dict[int, list[dict[str, Any]]] = {
            tire_id: [] for tire_id in tire_ids
        }
        if not tire_ids:
            return grouped

        result = await self.db.execute(
            select(
                TireChangeDocumentModel.id,
                TireChangeDocumentModel.tire_id,
                TireChangeDocumentModel.file_name,
                TireChangeDocumentModel.content_type,
                TireChangeDocumentModel.file_size,
                TireChangeDocumentModel.uploaded_by_id,
                UserModel.firstname,
                UserModel.lastname,
                TireChangeDocumentModel.created_at,
            )
            .outerjoin(
                UserModel,
                TireChangeDocumentModel.uploaded_by_id == UserModel.id,
            )
            .where(TireChangeDocumentModel.tire_id.in_(tire_ids))
            .order_by(
                TireChangeDocumentModel.created_at.asc(),
                TireChangeDocumentModel.id.asc(),
            )
        )
        for (
            document_id,
            tire_id,
            file_name,
            content_type,
            file_size,
            uploaded_by_id,
            firstname,
            lastname,
            created_at,
        ) in result.all():
            uploader_name = " ".join(
                part for part in (firstname, lastname) if part
            ).strip()
            grouped.setdefault(tire_id, []).append(
                {
                    "id": document_id,
                    "tire_id": tire_id,
                    "file_name": file_name,
                    "content_type": content_type or "application/pdf",
                    "file_size": file_size or 0,
                    "uploaded_by_id": uploaded_by_id,
                    "uploaded_by_name": uploader_name or None,
                    "created_at": created_at,
                }
            )
        return grouped

    async def _to_items(self, query) -> list[dict[str, Any]]:
        result = await self.db.execute(query)
        rows = result.all()
        documents = await self._documents_for([row[0].id for row in rows])
        return [
            self._row_to_item(row, documents.get(row[0].id, [])) for row in rows
        ]

    # ---------- READ ----------

    async def _fetch_items(
        self,
        *,
        search: Optional[str] = None,
        position: Optional[str] = None,
        machine_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        query = self._base_select()
        filters = []

        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                    TireChangeModel.position.ilike(pattern),
                    TireChangeModel.brand_model.ilike(pattern),
                    TireChangeModel.size.ilike(pattern),
                    TireChangeModel.change_reason.ilike(pattern),
                    TireChangeModel.km_hour.ilike(pattern),
                )
            )
        if position:
            filters.append(position_matches(TireChangeModel.position, position))
        if machine_id is not None:
            filters.append(TireChangeModel.machine_id == machine_id)
        if date_from is not None:
            filters.append(TireChangeModel.change_date >= date_from)
        if date_to is not None:
            filters.append(TireChangeModel.change_date <= date_to)

        if filters:
            query = query.where(*filters)

        query = query.order_by(
            TireChangeModel.change_date.desc(),
            TireChangeModel.id.desc(),
        )
        return await self._to_items(query)

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        position: Optional[str] = None,
        machine_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        items = await self._fetch_items(
            search=search,
            position=position,
            machine_id=machine_id,
            date_from=date_from,
            date_to=date_to,
        )
        return {
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    async def get_machine_options(
        self, *, search: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, MAX_MACHINE_OPTIONS))

        query = select(
            AllMachineModel,
            CarStatusModel.name.label("status_name"),
        ).outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)

        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )

        result = await self.db.execute(
            query.order_by(AllMachineModel.identification_no.asc()).limit(limit)
        )
        return [
            {
                "id": machine.id,
                "identification_no": machine.identification_no,
                "plate_no": machine.plate_no,
                "vin_no": machine.vin_no,
                "status_id": machine.status_id,
                "status_name": status_name,
            }
            for machine, status_name in result.all()
        ]

    async def get_history(
        self, tire_id: int, *, limit: int = MAX_HISTORY
    ) -> list[dict[str, Any]]:
        """Older changes of the same machine + position ("eski kayıtlar")."""

        change = await self.get_change(tire_id)
        limit = max(1, min(limit, MAX_HISTORY))

        query = (
            self._base_select()
            .where(
                TireChangeModel.machine_id == change.machine_id,
                position_matches(TireChangeModel.position, change.position),
                or_(
                    TireChangeModel.change_date < change.change_date,
                    and_(
                        TireChangeModel.change_date == change.change_date,
                        TireChangeModel.id < change.id,
                    ),
                ),
            )
            .order_by(
                TireChangeModel.change_date.desc(),
                TireChangeModel.id.desc(),
            )
            .limit(limit)
        )
        return await self._to_items(query)

    # ---------- WRITE ----------

    async def _require_machine(self, machine_id: int) -> AllMachineModel:
        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")
        return machine

    async def get_change(self, tire_id: int) -> TireChangeModel:
        change = await self.db.get(TireChangeModel, tire_id)
        if change is None:
            raise HTTPException(
                status_code=404, detail="Lastik kaydı bulunamadı"
            )
        return change

    async def get_item(self, tire_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._base_select().where(TireChangeModel.id == tire_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Lastik kaydı bulunamadı"
            )
        documents = await self._documents_for([tire_id])
        return self._row_to_item(row, documents.get(tire_id, []))

    async def create_change(
        self, data: TireChangeCreateSchema, user_id: Optional[int]
    ) -> dict[str, Any]:
        await self._require_machine(data.machine_id)

        change = TireChangeModel(
            machine_id=data.machine_id,
            position=normalize_position(data.position),
            brand_model=data.brand_model,
            size=data.size,
            change_reason=data.change_reason,
            km_hour=data.km_hour,
            change_date=data.change_date or date.today(),
            created_by_id=user_id,
        )
        self.db.add(change)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Lastik kaydı oluşturulamadı"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        await self.db.refresh(change)
        return await self.get_item(change.id)

    async def add_document(
        self,
        tire_id: int,
        *,
        file_name: Optional[str],
        content_type: Optional[str],
        data: bytes,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        change = await self.get_change(tire_id)

        try:
            info = validate_document(
                file_name,
                content_type,
                data,
                max_bytes=MAX_TIRE_DOCUMENT_BYTES,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document = TireChangeDocumentModel(
            tire_id=change.id,
            file_name=info["file_name"],
            content_type=info["content_type"],
            file_size=info["file_size"],
            file_data=data,
            uploaded_by_id=user_id,
        )
        self.db.add(document)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Evrak kaydedilemedi"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        return await self.get_item(change.id)

    async def get_document(
        self, tire_id: int, document_id: int
    ) -> TireChangeDocumentModel:
        document = await self.db.get(TireChangeDocumentModel, document_id)
        if document is None or document.tire_id != tire_id:
            raise HTTPException(status_code=404, detail="Evrak bulunamadı")
        return document

    async def delete_document(
        self, tire_id: int, document_id: int
    ) -> dict[str, Any]:
        document = await self.get_document(tire_id, document_id)
        await self.db.delete(document)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return await self.get_item(tire_id)
