# repositories/purchase_request_repository.py
"""Database access for spare-part and service purchase requests."""

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import AllMachineModel, TerritoryModel
from models.purchase_request_model import (
    MAX_DOCUMENT_BYTES,
    SPARE_PART_STATUSES,
    ServiceRequestModel,
    SparePartRequestDocumentModel,
    SparePartRequestItemModel,
    SparePartRequestModel,
    SparePartRequestTypeModel,
    status_label,
)
from models.user_model import UserModel
from repositories.pdf_documents import validate_document
from schemas.purchase_request_schemas import (
    ServiceRequestCreateSchema,
    SparePartRequestCreateSchema,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_MACHINE_OPTIONS = 50


# =========================================================
# PURE HELPERS (unit tested without a database)
# =========================================================

def clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    """Keep client supplied paging inside the API limits."""

    limit = DEFAULT_LIMIT if limit < 1 else min(limit, MAX_LIMIT)
    offset = max(offset, 0)
    return limit, offset


def build_search_pattern(search: Optional[str]) -> Optional[str]:
    """``None`` for a blank box so the query stays unfiltered."""

    search = (search or "").strip()
    return f"%{search}%" if search else None


def machine_label(
    identification_no: Optional[str],
    plate_no: Optional[str],
    vin_no: Optional[str],
    machine_id: int,
) -> str:
    """What the "ID No" column shows; falls back to the database id."""

    return (
        (identification_no or "").strip()
        or (plate_no or "").strip()
        or (vin_no or "").strip()
        or f"Makine #{machine_id}"
    )


def validate_status_filter(status: Optional[str]) -> Optional[str]:
    """Filter values come from a query string, so validate them here."""

    if status is None or not str(status).strip():
        return None
    status = str(status).strip().lower()
    if status not in SPARE_PART_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Talep durumu yalnızca 'geldi' veya 'bekleniyor' olabilir",
        )
    return status


# =========================================================
# REPOSITORY
# =========================================================

class PurchaseRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- SHARED HELPERS ----------

    @staticmethod
    def _creator_name(
        firstname: Optional[str], lastname: Optional[str]
    ) -> Optional[str]:
        name = " ".join(part for part in (firstname, lastname) if part).strip()
        return name or None

    async def _require(self, model, obj_id: int, message: str):
        obj = await self.db.get(model, obj_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=message)
        return obj

    # ---------- SPARE PART REQUESTS ----------

    def _spare_select(self):
        return (
            select(
                SparePartRequestModel,
                TerritoryModel.name.label("territory_name"),
                SparePartRequestTypeModel.name.label("request_type_name"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(SparePartRequestModel)
            .join(
                TerritoryModel,
                SparePartRequestModel.territory_id == TerritoryModel.id,
            )
            .join(
                SparePartRequestTypeModel,
                SparePartRequestModel.request_type_id
                == SparePartRequestTypeModel.id,
            )
            .outerjoin(
                UserModel, SparePartRequestModel.created_by_id == UserModel.id
            )
        )

    async def _spare_rows(
        self,
        *,
        search: Optional[str] = None,
        identification_no: Optional[str] = None,
        status: Optional[str] = None,
        territory_id: Optional[int] = None,
        request_type_id: Optional[int] = None,
        date_from=None,
        date_to=None,
    ):
        query = self._spare_select()

        pattern = build_search_pattern(search)
        if pattern:
            # Machine / garage numbers live on the item rows, so search them
            # through correlated EXISTS sub-queries instead of a JOIN that
            # would duplicate the request rows.
            machine_match = (
                select(SparePartRequestItemModel.id)
                .join(
                    AllMachineModel,
                    SparePartRequestItemModel.machine_id == AllMachineModel.id,
                )
                .where(
                    SparePartRequestItemModel.request_id
                    == SparePartRequestModel.id,
                    or_(
                        AllMachineModel.identification_no.ilike(pattern),
                        AllMachineModel.plate_no.ilike(pattern),
                        AllMachineModel.vin_no.ilike(pattern),
                    ),
                )
                .exists()
            )
            garage_match = (
                select(SparePartRequestItemModel.id)
                .where(
                    SparePartRequestItemModel.request_id
                    == SparePartRequestModel.id,
                    SparePartRequestItemModel.garage_request_no.ilike(pattern),
                )
                .exists()
            )
            query = query.where(
                or_(
                    SparePartRequestModel.title.ilike(pattern),
                    SparePartRequestModel.stf_htf_no.ilike(pattern),
                    machine_match,
                    garage_match,
                )
            )

        machine_pattern = build_search_pattern(identification_no)
        if machine_pattern:
            # Excel-style "ID No" column filter: match the machine numbers of
            # the request's item rows without duplicating the request itself.
            query = query.where(
                select(SparePartRequestItemModel.id)
                .join(
                    AllMachineModel,
                    SparePartRequestItemModel.machine_id == AllMachineModel.id,
                )
                .where(
                    SparePartRequestItemModel.request_id
                    == SparePartRequestModel.id,
                    or_(
                        AllMachineModel.identification_no.ilike(machine_pattern),
                        AllMachineModel.plate_no.ilike(machine_pattern),
                        AllMachineModel.vin_no.ilike(machine_pattern),
                    ),
                )
                .exists()
            )

        if status:
            query = query.where(SparePartRequestModel.status == status)
        if territory_id:
            query = query.where(
                SparePartRequestModel.territory_id == territory_id
            )
        if request_type_id:
            query = query.where(
                SparePartRequestModel.request_type_id == request_type_id
            )
        if date_from:
            query = query.where(SparePartRequestModel.request_date >= date_from)
        if date_to:
            query = query.where(SparePartRequestModel.request_date <= date_to)

        result = await self.db.execute(
            query.order_by(
                SparePartRequestModel.request_date.desc(),
                SparePartRequestModel.id.desc(),
            )
        )
        return result.all()

    async def _items_for(
        self, request_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {
            request_id: [] for request_id in request_ids
        }
        if not request_ids:
            return grouped

        result = await self.db.execute(
            select(
                SparePartRequestItemModel,
                AllMachineModel.identification_no,
                AllMachineModel.plate_no,
                AllMachineModel.vin_no,
            )
            .join(
                AllMachineModel,
                SparePartRequestItemModel.machine_id == AllMachineModel.id,
            )
            .where(SparePartRequestItemModel.request_id.in_(request_ids))
            .order_by(SparePartRequestItemModel.id.asc())
        )

        for item, identification_no, plate_no, vin_no in result.all():
            grouped[item.request_id].append(
                {
                    "id": item.id,
                    "machine_id": item.machine_id,
                    "identification_no": identification_no,
                    "plate_no": plate_no,
                    "vin_no": vin_no,
                    "garage_request_no": item.garage_request_no,
                    "part_number": item.part_number,
                    "description_ru": item.description_ru,
                    "description_tr": item.description_tr,
                    "quantity": float(item.quantity or 0),
                    "unit": item.unit,
                    "supply_date": item.supply_date,
                }
            )
        return grouped

    async def _documents_for(
        self, request_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Document metadata of every request; the PDF bytes stay untouched."""

        grouped: dict[int, list[dict[str, Any]]] = {
            request_id: [] for request_id in request_ids
        }
        if not request_ids:
            return grouped

        result = await self.db.execute(
            select(SparePartRequestDocumentModel)
            .where(SparePartRequestDocumentModel.request_id.in_(request_ids))
            .order_by(SparePartRequestDocumentModel.id.asc())
        )

        for document in result.scalars().all():
            grouped[document.request_id].append(
                {
                    "id": document.id,
                    "file_name": document.file_name,
                    "content_type": document.content_type,
                    "file_size": document.file_size,
                    "created_at": document.created_at,
                }
            )
        return grouped

    def _spare_row_to_item(
        self,
        row,
        items: list[dict[str, Any]],
        documents: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        request: SparePartRequestModel = row[0]

        machine_ids: list[int] = []
        machine_labels: list[str] = []
        for item in items:
            if item["machine_id"] in machine_ids:
                continue
            machine_ids.append(item["machine_id"])
            machine_labels.append(
                machine_label(
                    item["identification_no"],
                    item["plate_no"],
                    item["vin_no"],
                    item["machine_id"],
                )
            )

        return {
            "id": request.id,
            "title": request.title,
            "stf_htf_no": request.stf_htf_no,
            "territory_id": request.territory_id,
            "territory_name": row.territory_name,
            "request_type_id": request.request_type_id,
            "request_type_name": row.request_type_name,
            "request_date": request.request_date,
            "status": request.status,
            "status_label": status_label(request.status),
            "machine_ids": machine_ids,
            "machine_labels": machine_labels,
            "item_count": len(items),
            "created_by_id": request.created_by_id,
            "created_by_name": self._creator_name(
                row.creator_firstname, row.creator_lastname
            ),
            "created_at": request.created_at,
            "updated_at": request.updated_at,
            "items": items,
            "documents": documents or [],
        }

    async def _get_spare_request(self, request_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._spare_select().where(SparePartRequestModel.id == request_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Yedek parça talebi bulunamadı"
            )
        items = await self._items_for([request_id])
        documents = await self._documents_for([request_id])
        return self._spare_row_to_item(
            row,
            items.get(request_id, []),
            documents.get(request_id, []),
        )

    async def fetch_spare_part_requests(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        identification_no: Optional[str] = None,
        status: Optional[str] = None,
        territory_id: Optional[int] = None,
        request_type_id: Optional[int] = None,
        date_from=None,
        date_to=None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        rows = await self._spare_rows(
            search=search,
            identification_no=identification_no,
            status=status,
            territory_id=territory_id,
            request_type_id=request_type_id,
            date_from=date_from,
            date_to=date_to,
        )

        page = rows[offset : offset + limit]
        items = await self._items_for([row[0].id for row in page])
        documents = await self._documents_for([row[0].id for row in page])
        return {
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "items": [
                self._spare_row_to_item(
                    row,
                    items.get(row[0].id, []),
                    documents.get(row[0].id, []),
                )
                for row in page
            ],
        }

    async def list_request_types(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(SparePartRequestTypeModel).order_by(
                SparePartRequestTypeModel.id.asc()
            )
        )
        return [
            {"id": request_type.id, "name": request_type.name}
            for request_type in result.scalars().all()
        ]

    async def get_machine_options(
        self, *, search: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, MAX_MACHINE_OPTIONS))

        query = select(AllMachineModel)
        pattern = build_search_pattern(search)
        if pattern:
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
            }
            for machine in result.scalars().all()
        ]

    # ---------- SPARE PART WRITE ----------

    async def create_spare_part_request(
        self, data: SparePartRequestCreateSchema, user_id: Optional[int]
    ) -> dict[str, Any]:
        await self._require(
            TerritoryModel, data.territory_id, "Şantiye bulunamadı"
        )
        await self._require(
            SparePartRequestTypeModel,
            data.request_type_id,
            "Talep türü bulunamadı",
        )

        machine_ids = sorted({item.machine_id for item in data.items})
        result = await self.db.execute(
            select(AllMachineModel.id).where(AllMachineModel.id.in_(machine_ids))
        )
        found = set(result.scalars().all())
        missing = [
            machine_id for machine_id in machine_ids if machine_id not in found
        ]
        if missing:
            raise HTTPException(
                status_code=404,
                detail="Makine bulunamadı: "
                + ", ".join(str(machine_id) for machine_id in missing),
            )

        request = SparePartRequestModel(
            title=data.title,
            stf_htf_no=data.stf_htf_no,
            territory_id=data.territory_id,
            request_type_id=data.request_type_id,
            request_date=data.request_date,
            status=data.status,
            created_by_id=user_id,
            items=[
                SparePartRequestItemModel(
                    machine_id=item.machine_id,
                    garage_request_no=item.garage_request_no,
                    part_number=item.part_number,
                    description_ru=item.description_ru,
                    description_tr=item.description_tr,
                    quantity=item.quantity,
                    unit=item.unit,
                    supply_date=item.supply_date,
                )
                for item in data.items
            ],
        )
        self.db.add(request)
        try:
            await self.db.flush()
            request_id = request.id
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Yedek parça talebi kaydedilemedi"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        return await self._get_spare_request(request_id)

    async def update_spare_status(
        self, request_id: int, status: str
    ) -> dict[str, Any]:
        request = await self.db.get(SparePartRequestModel, request_id)
        if request is None:
            raise HTTPException(
                status_code=404, detail="Yedek parça talebi bulunamadı"
            )
        request.status = status
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return await self._get_spare_request(request_id)

    async def delete_spare_part_request(self, request_id: int) -> None:
        request = await self.db.get(SparePartRequestModel, request_id)
        if request is None:
            raise HTTPException(
                status_code=404, detail="Yedek parça talebi bulunamadı"
            )
        await self.db.delete(request)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    # ---------- SPARE PART DOCUMENTS ----------

    async def add_document(
        self,
        request_id: int,
        *,
        file_name: Optional[str],
        content_type: Optional[str],
        data: bytes,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        """Attach a PDF to a request; the request row is returned with it."""

        request = await self.db.get(SparePartRequestModel, request_id)
        if request is None:
            raise HTTPException(
                status_code=404, detail="Yedek parça talebi bulunamadı"
            )

        try:
            info = validate_document(
                file_name,
                content_type,
                data,
                max_bytes=MAX_DOCUMENT_BYTES,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document = SparePartRequestDocumentModel(
            request_id=request.id,
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
        return await self._get_spare_request(request.id)

    async def get_document(
        self, request_id: int, document_id: int
    ) -> SparePartRequestDocumentModel:
        document = await self.db.get(SparePartRequestDocumentModel, document_id)
        if document is None or document.request_id != request_id:
            raise HTTPException(status_code=404, detail="Evrak bulunamadı")
        return document

    async def delete_document(
        self, request_id: int, document_id: int
    ) -> dict[str, Any]:
        document = await self.get_document(request_id, document_id)
        await self.db.delete(document)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return await self._get_spare_request(request_id)

    # ---------- SERVICE REQUESTS ----------

    def _service_select(self):
        return (
            select(
                ServiceRequestModel,
                AllMachineModel.identification_no.label("identification_no"),
                AllMachineModel.plate_no.label("plate_no"),
                AllMachineModel.vin_no.label("vin_no"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(ServiceRequestModel)
            .join(
                AllMachineModel, ServiceRequestModel.machine_id == AllMachineModel.id
            )
            .outerjoin(UserModel, ServiceRequestModel.created_by_id == UserModel.id)
        )

    async def _service_rows(
        self,
        *,
        search: Optional[str] = None,
        identification_no: Optional[str] = None,
        company_name: Optional[str] = None,
        service_description: Optional[str] = None,
        date_from=None,
        date_to=None,
    ):
        query = self._service_select()

        pattern = build_search_pattern(search)
        if pattern:
            query = query.where(
                or_(
                    ServiceRequestModel.title.ilike(pattern),
                    ServiceRequestModel.service_form_no.ilike(pattern),
                    ServiceRequestModel.company_name.ilike(pattern),
                    ServiceRequestModel.service_description.ilike(pattern),
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )

        if date_from:
            query = query.where(ServiceRequestModel.request_date >= date_from)
        if date_to:
            query = query.where(ServiceRequestModel.request_date <= date_to)

        # Excel-style column filters — each one narrows a single table column.
        machine_pattern = build_search_pattern(identification_no)
        if machine_pattern:
            query = query.where(
                or_(
                    AllMachineModel.identification_no.ilike(machine_pattern),
                    AllMachineModel.plate_no.ilike(machine_pattern),
                    AllMachineModel.vin_no.ilike(machine_pattern),
                )
            )
        company_pattern = build_search_pattern(company_name)
        if company_pattern:
            query = query.where(
                ServiceRequestModel.company_name.ilike(company_pattern)
            )
        description_pattern = build_search_pattern(service_description)
        if description_pattern:
            query = query.where(
                ServiceRequestModel.service_description.ilike(description_pattern)
            )

        result = await self.db.execute(
            query.order_by(
                ServiceRequestModel.request_date.desc(),
                ServiceRequestModel.id.desc(),
            )
        )
        return result.all()

    def _service_row_to_item(self, row) -> dict[str, Any]:
        request: ServiceRequestModel = row[0]
        return {
            "id": request.id,
            "title": request.title,
            "service_form_no": request.service_form_no,
            "machine_id": request.machine_id,
            "identification_no": row.identification_no,
            "plate_no": row.plate_no,
            "vin_no": row.vin_no,
            "company_name": request.company_name,
            "service_description": request.service_description,
            "request_date": request.request_date,
            "created_by_id": request.created_by_id,
            "created_by_name": self._creator_name(
                row.creator_firstname, row.creator_lastname
            ),
            "created_at": request.created_at,
            "updated_at": request.updated_at,
        }

    async def _get_service_request(self, request_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._service_select().where(ServiceRequestModel.id == request_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Servis/hizmet talebi bulunamadı"
            )
        return self._service_row_to_item(row)

    async def fetch_service_requests(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        identification_no: Optional[str] = None,
        company_name: Optional[str] = None,
        service_description: Optional[str] = None,
        date_from=None,
        date_to=None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        rows = await self._service_rows(
            search=search,
            identification_no=identification_no,
            company_name=company_name,
            service_description=service_description,
            date_from=date_from,
            date_to=date_to,
        )
        return {
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "items": [
                self._service_row_to_item(row)
                for row in rows[offset : offset + limit]
            ],
        }

    async def create_service_request(
        self, data: ServiceRequestCreateSchema, user_id: Optional[int]
    ) -> dict[str, Any]:
        await self._require(AllMachineModel, data.machine_id, "Makine bulunamadı")

        request = ServiceRequestModel(
            title=data.title,
            service_form_no=data.service_form_no,
            machine_id=data.machine_id,
            company_name=data.company_name,
            service_description=data.service_description,
            request_date=data.request_date,
            created_by_id=user_id,
        )
        self.db.add(request)
        try:
            await self.db.flush()
            request_id = request.id
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Servis/hizmet talebi kaydedilemedi"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        return await self._get_service_request(request_id)

    async def delete_service_request(self, request_id: int) -> None:
        request = await self.db.get(ServiceRequestModel, request_id)
        if request is None:
            raise HTTPException(
                status_code=404, detail="Servis/hizmet talebi bulunamadı"
            )
        await self.db.delete(request)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_MACHINE_OPTIONS",
    "PurchaseRequestRepository",
    "build_search_pattern",
    "clamp_pagination",
    "machine_label",
    "validate_status_filter",
]
