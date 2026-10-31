# repositories/daily_fault_repository.py
"""Database access for daily (quick) faults and their PDF documents."""

from datetime import date
from typing import Any, Optional
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.daily_fault_model import (
    MAX_DOCUMENT_BYTES,
    DailyFaultDocumentModel,
    DailyFaultModel,
)
from models.machines_model import (
    AllMachineModel,
    CarMarkModel,
    CarModelModel,
    CarStatusModel,
    TerritoryModel,
)
from models.repair_model import RepairTypeModel
from models.user_model import UserModel
from schemas.daily_fault_schemas import DailyFaultCreateSchema, normalize_km_hour

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_MACHINE_OPTIONS = 50

#: Browsers occasionally send "application/x-pdf"; both mean the same file.
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
}
#: Some browsers submit an empty type (or octet-stream) for local files.
_FALLBACK_DOCUMENT_TYPES = {"", "application/octet-stream"}
_PDF_SIGNATURE = b"%PDF-"
_FALLBACK_DOCUMENT_NAME = "evrak.pdf"


# =========================================================
# PURE HELPERS (unit tested without a database)
# =========================================================

def clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    """Keep client supplied paging inside the API limits."""

    limit = DEFAULT_LIMIT if limit < 1 else min(limit, MAX_LIMIT)
    offset = max(offset, 0)
    return limit, offset


def sanitize_file_name(file_name: Optional[str]) -> str:
    """Take the base name only: never trust a path sent by the browser."""

    name = (file_name or "").replace("\\", "/").split("/")[-1].strip()
    name = name[:255].strip()
    return name or _FALLBACK_DOCUMENT_NAME


def resolve_document_content_type(
    file_name: str, content_type: Optional[str]
) -> str:
    """Normalize the browser supplied type; only PDFs are accepted."""

    raw = (content_type or "").split(";")[0].strip().lower()
    if raw in ALLOWED_DOCUMENT_TYPES:
        return "application/pdf"
    if raw in _FALLBACK_DOCUMENT_TYPES and file_name.lower().endswith(".pdf"):
        return "application/pdf"
    raise ValueError("Sadece PDF dosyaları yüklenebilir")


def validate_document(
    file_name: Optional[str], content_type: Optional[str], data: bytes
) -> dict[str, Any]:
    """Validate an uploaded paper; raises ``ValueError`` with a Turkish text."""

    if not data:
        raise ValueError("Boş dosya yüklenemez")

    if len(data) > MAX_DOCUMENT_BYTES:
        limit_mb = MAX_DOCUMENT_BYTES // (1024 * 1024)
        raise ValueError(f"Evrak boyutu en fazla {limit_mb} MB olabilir")

    resolved_name = sanitize_file_name(file_name)
    resolved_type = resolve_document_content_type(
        file_name or resolved_name, content_type
    )

    # Content type and extension are client supplied; the signature is not.
    if not data.startswith(_PDF_SIGNATURE):
        raise ValueError("Dosya geçerli bir PDF değil")

    return {
        "file_name": resolved_name,
        "content_type": resolved_type,
        "file_size": len(data),
    }


def content_disposition(file_name: str, *, download: bool = False) -> str:
    """RFC 5987 header so Turkish file names survive the download."""

    disposition = "attachment" if download else "inline"
    name = sanitize_file_name(file_name)
    ascii_name = (
        name.encode("ascii", "ignore").decode("ascii") or _FALLBACK_DOCUMENT_NAME
    )
    # Quotes would break the quoted-string parameter; filename* keeps the real name.
    ascii_name = ascii_name.replace('"', "_")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )


# =========================================================
# REPOSITORY
# =========================================================

class DailyFaultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    def _base_select(self):
        return (
            select(
                DailyFaultModel,
                AllMachineModel,
                TerritoryModel.name.label("territory_name"),
                RepairTypeModel.name.label("repair_type_name"),
                CarStatusModel.name.label("machine_status_name"),
                CarMarkModel.name.label("car_mark_name"),
                CarModelModel.name.label("car_model_name"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(DailyFaultModel)
            .join(AllMachineModel, DailyFaultModel.machine_id == AllMachineModel.id)
            .join(TerritoryModel, DailyFaultModel.territory_id == TerritoryModel.id)
            .join(
                RepairTypeModel,
                DailyFaultModel.repair_type_id == RepairTypeModel.id,
            )
            .outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)
            .outerjoin(CarMarkModel, AllMachineModel.car_mark_id == CarMarkModel.id)
            .outerjoin(CarModelModel, AllMachineModel.car_model_id == CarModelModel.id)
            .outerjoin(UserModel, DailyFaultModel.created_by_id == UserModel.id)
        )

    def _row_to_item(self, row, documents: Optional[list[dict[str, Any]]] = None):
        fault: DailyFaultModel = row[0]
        machine: AllMachineModel = row[1]
        creator_name = " ".join(
            part for part in (row.creator_firstname, row.creator_lastname) if part
        ).strip()

        return {
            "id": fault.id,
            "machine_id": machine.id,
            "identification_no": machine.identification_no,
            "plate_no": machine.plate_no,
            "vin_no": machine.vin_no,
            "car_mark_name": row.car_mark_name,
            "car_model_name": row.car_model_name,
            "machine_status_name": row.machine_status_name,
            "territory_id": fault.territory_id,
            "territory_name": row.territory_name,
            "repair_type_id": fault.repair_type_id,
            "repair_type_name": row.repair_type_name,
            "km_hour": fault.km_hour,
            "fault_assignment": fault.fault_assignment,
            "changed_parts": fault.changed_parts,
            "fault_date": fault.fault_date,
            "created_by_id": fault.created_by_id,
            "created_by_name": creator_name or None,
            "created_at": fault.created_at,
            "updated_at": fault.updated_at,
            "documents": documents or [],
        }

    async def _documents_for(
        self, fault_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Document metadata only: the PDF bytes never enter the list query."""

        grouped: dict[int, list[dict[str, Any]]] = {
            fault_id: [] for fault_id in fault_ids
        }
        if not fault_ids:
            return grouped

        result = await self.db.execute(
            select(
                DailyFaultDocumentModel.id,
                DailyFaultDocumentModel.fault_id,
                DailyFaultDocumentModel.file_name,
                DailyFaultDocumentModel.content_type,
                DailyFaultDocumentModel.file_size,
                DailyFaultDocumentModel.uploaded_by_id,
                UserModel.firstname,
                UserModel.lastname,
                DailyFaultDocumentModel.created_at,
            )
            .outerjoin(
                UserModel,
                DailyFaultDocumentModel.uploaded_by_id == UserModel.id,
            )
            .where(DailyFaultDocumentModel.fault_id.in_(fault_ids))
            .order_by(
                DailyFaultDocumentModel.created_at.asc(),
                DailyFaultDocumentModel.id.asc(),
            )
        )
        for (
            document_id,
            fault_id,
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
            grouped.setdefault(fault_id, []).append(
                {
                    "id": document_id,
                    "fault_id": fault_id,
                    "file_name": file_name,
                    "content_type": content_type or "application/pdf",
                    "file_size": file_size or 0,
                    "uploaded_by_id": uploaded_by_id,
                    "uploaded_by_name": uploader_name or None,
                    "created_at": created_at,
                }
            )
        return grouped

    # ---------- READ ----------

    async def _fetch_items(
        self,
        *,
        search: Optional[str] = None,
        territory_id: Optional[int] = None,
        repair_type_id: Optional[int] = None,
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
                    DailyFaultModel.km_hour.ilike(pattern),
                    DailyFaultModel.fault_assignment.ilike(pattern),
                    DailyFaultModel.changed_parts.ilike(pattern),
                    TerritoryModel.name.ilike(pattern),
                    RepairTypeModel.name.ilike(pattern),
                )
            )
        if territory_id is not None:
            filters.append(DailyFaultModel.territory_id == territory_id)
        if repair_type_id is not None:
            filters.append(DailyFaultModel.repair_type_id == repair_type_id)
        if date_from is not None:
            filters.append(DailyFaultModel.fault_date >= date_from)
        if date_to is not None:
            filters.append(DailyFaultModel.fault_date <= date_to)

        if filters:
            query = query.where(*filters)

        query = query.order_by(
            DailyFaultModel.fault_date.desc(),
            DailyFaultModel.id.desc(),
        )
        result = await self.db.execute(query)
        rows = result.all()
        documents = await self._documents_for([row[0].id for row in rows])
        return [
            self._row_to_item(row, documents.get(row[0].id, [])) for row in rows
        ]

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        territory_id: Optional[int] = None,
        repair_type_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        items = await self._fetch_items(
            search=search,
            territory_id=territory_id,
            repair_type_id=repair_type_id,
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

    # ---------- WRITE ----------

    async def _require(self, model, obj_id: int, message: str):
        obj = await self.db.get(model, obj_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=message)
        return obj

    async def _get_fault(self, fault_id: int) -> DailyFaultModel:
        fault = await self.db.get(DailyFaultModel, fault_id)
        if fault is None:
            raise HTTPException(
                status_code=404, detail="Günlük arıza kaydı bulunamadı"
            )
        return fault

    async def _get_item(self, fault_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._base_select().where(DailyFaultModel.id == fault_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Günlük arıza kaydı bulunamadı"
            )
        documents = await self._documents_for([fault_id])
        return self._row_to_item(row, documents.get(fault_id, []))

    async def create_fault(
        self, data: DailyFaultCreateSchema, user_id: Optional[int]
    ) -> dict[str, Any]:
        await self._require(AllMachineModel, data.machine_id, "Makine bulunamadı")
        await self._require(TerritoryModel, data.territory_id, "Şantiye bulunamadı")
        await self._require(
            RepairTypeModel, data.repair_type_id, "Arıza tipi bulunamadı"
        )

        fault = DailyFaultModel(
            machine_id=data.machine_id,
            territory_id=data.territory_id,
            repair_type_id=data.repair_type_id,
            km_hour=normalize_km_hour(data.km_hour),
            fault_assignment=data.fault_assignment,
            changed_parts=data.changed_parts,
            fault_date=date.today(),
            created_by_id=user_id,
        )
        self.db.add(fault)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Günlük arıza kaydı oluşturulamadı",
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        await self.db.refresh(fault)
        return await self._get_item(fault.id)

    async def add_document(
        self,
        fault_id: int,
        *,
        file_name: Optional[str],
        content_type: Optional[str],
        data: bytes,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        fault = await self._get_fault(fault_id)

        try:
            info = validate_document(file_name, content_type, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document = DailyFaultDocumentModel(
            fault_id=fault.id,
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
        return await self._get_item(fault.id)

    async def get_document(
        self, fault_id: int, document_id: int
    ) -> DailyFaultDocumentModel:
        document = await self.db.get(DailyFaultDocumentModel, document_id)
        if document is None or document.fault_id != fault_id:
            raise HTTPException(status_code=404, detail="Evrak bulunamadı")
        return document

    async def delete_document(
        self, fault_id: int, document_id: int
    ) -> dict[str, Any]:
        document = await self.get_document(fault_id, document_id)
        await self.db.delete(document)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return await self._get_item(fault_id)



