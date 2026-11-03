# repositories/warehouse_repository.py
"""Database access for the warehouse (ambar) module.

The stock card balance is *derived state*: every write goes through
``create_movement`` (manual in/out) or ``receive_items`` (arrived purchasing
rows), both of which run ``apply_movement`` so the cached ``quantity`` always
matches the ledger. The database keeps the same promise with
``ck_warehouse_items_quantity_not_negative``.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import AllMachineModel, TerritoryModel
from models.purchase_request_model import (
    SparePartRequestItemModel,
    SparePartRequestModel,
    SparePartRequestTypeModel,
)
from models.user_model import UserModel
from models.warehouse_model import (
    MOVEMENT_IN,
    MOVEMENT_OUT,
    MOVEMENT_TYPES,
    WarehouseItemModel,
    WarehouseMovementModel,
    movement_type_label,
    quantize_quantity,
    stock_status,
    stock_status_label,
)
from schemas.warehouse_schemas import (
    WarehouseItemCreateSchema,
    WarehouseItemUpdateSchema,
    WarehouseMovementCreateSchema,
    WarehouseReceiptCreateSchema,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: Request status that allows the warehouse to take the part into stock.
ARRIVED_STATUS = "geldi"


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


def normalize_part_number(value: Optional[str]) -> Optional[str]:
    """Part numbers are compared case/space insensitively."""

    value = " ".join((value or "").split())
    return value.upper() or None


def validate_movement_type(value: Optional[str]) -> str:
    """Filter/body values arrive as free text, so validate them here."""

    movement_type = (value or "").strip().lower()
    if movement_type not in MOVEMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Hareket tipi yalnızca 'giris' veya 'cikis' olabilir",
        )
    return movement_type


def quantity_text(value) -> str:
    """``Decimal('2.000')`` -> ``"2"``, ``Decimal('2.500')`` -> ``"2.5"``."""

    return f"{quantize_quantity(value).normalize():f}"


def apply_movement(
    current_quantity,
    movement_type: str,
    quantity,
    item_name: Optional[str] = None,
) -> Decimal:
    """Return the balance after an in/out line; raise 400 when stock is short."""

    movement_type = validate_movement_type(movement_type)

    current = quantize_quantity(current_quantity)
    amount = quantize_quantity(quantity)

    if amount <= 0:
        raise HTTPException(
            status_code=400, detail="Miktar sıfırdan büyük olmalı"
        )

    if movement_type == MOVEMENT_IN:
        return quantize_quantity(current + amount)

    if amount > current:
        label = item_name or "stok kartı"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Yetersiz stok: {label} için mevcut {quantity_text(current)}, "
                f"istenen {quantity_text(amount)}"
            ),
        )

    return quantize_quantity(current - amount)


def machine_label(
    identification_no: Optional[str],
    plate_no: Optional[str],
    vin_no: Optional[str],
    machine_id: Optional[int] = None,
) -> str:
    """What the "Makine" column shows; falls back to the database id."""

    label = (
        (identification_no or "").strip()
        or (plate_no or "").strip()
        or (vin_no or "").strip()
    )
    if label:
        return label
    return f"Makine #{machine_id}" if machine_id else "—"


# =========================================================
# REPOSITORY
# =========================================================

class WarehouseRepository:
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

    async def _require_territory(self, territory_id: Optional[int]) -> None:
        if territory_id is None:
            return
        await self._require(TerritoryModel, territory_id, "Bölge bulunamadı")

    async def _commit(self, message: str) -> None:
        """Commit, translating constraint violations into a readable 409."""

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail=message) from exc
        except Exception:
            await self.db.rollback()
            raise

    # ---------- STOCK CARDS ----------

    def _stock_select(self):
        return (
            select(
                WarehouseItemModel,
                TerritoryModel.name.label("territory_name"),
            )
            .select_from(WarehouseItemModel)
            .outerjoin(
                TerritoryModel,
                WarehouseItemModel.territory_id == TerritoryModel.id,
            )
        )

    def _stock_row_to_item(
        self, row, movement_count: int = 0
    ) -> dict[str, Any]:
        item: WarehouseItemModel = row[0]
        status = stock_status(item.quantity, item.min_quantity)

        return {
            "id": item.id,
            "name": item.name,
            "part_number": item.part_number,
            "description_tr": item.description_tr,
            "description_ru": item.description_ru,
            "unit": item.unit,
            "territory_id": item.territory_id,
            "territory_name": row.territory_name,
            "location": item.location,
            "min_quantity": float(item.min_quantity or 0),
            "quantity": float(item.quantity or 0),
            "stock_status": status,
            "stock_status_label": stock_status_label(status),
            "movement_count": movement_count,
            "notes": item.notes,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    async def _movement_counts(self, item_ids: list[int]) -> dict[int, int]:
        if not item_ids:
            return {}
        result = await self.db.execute(
            select(
                WarehouseMovementModel.item_id,
                func.count(WarehouseMovementModel.id),
            )
            .where(WarehouseMovementModel.item_id.in_(item_ids))
            .group_by(WarehouseMovementModel.item_id)
        )
        return {item_id: count for item_id, count in result.all()}

    def _stock_conditions(
        self,
        *,
        search: Optional[str],
        territory_id: Optional[int],
        low_stock: bool,
    ) -> list:
        conditions = []

        pattern = build_search_pattern(search)
        if pattern:
            conditions.append(
                or_(
                    WarehouseItemModel.name.ilike(pattern),
                    WarehouseItemModel.part_number.ilike(pattern),
                    WarehouseItemModel.description_tr.ilike(pattern),
                    WarehouseItemModel.description_ru.ilike(pattern),
                    WarehouseItemModel.location.ilike(pattern),
                )
            )
        if territory_id:
            conditions.append(WarehouseItemModel.territory_id == territory_id)
        if low_stock:
            conditions.append(
                WarehouseItemModel.quantity <= WarehouseItemModel.min_quantity
            )

        return conditions

    async def fetch_stock(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        territory_id: Optional[int] = None,
        low_stock: bool = False,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        conditions = self._stock_conditions(
            search=search, territory_id=territory_id, low_stock=low_stock
        )

        count_query = select(func.count()).select_from(WarehouseItemModel)
        rows_query = self._stock_select()
        if conditions:
            count_query = count_query.where(and_(*conditions))
            rows_query = rows_query.where(and_(*conditions))

        total = (await self.db.execute(count_query)).scalar_one()
        result = await self.db.execute(
            rows_query.order_by(
                WarehouseItemModel.name.asc(), WarehouseItemModel.id.asc()
            )
            .limit(limit)
            .offset(offset)
        )
        rows = result.all()
        counts = await self._movement_counts([row[0].id for row in rows])

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                self._stock_row_to_item(row, counts.get(row[0].id, 0))
                for row in rows
            ],
        }

    async def get_stock(self, item_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._stock_select().where(WarehouseItemModel.id == item_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Stok kartı bulunamadı")

        counts = await self._movement_counts([item_id])
        return self._stock_row_to_item(row, counts.get(item_id, 0))

    async def _ensure_unique_part_number(
        self, part_number: Optional[str], exclude_id: Optional[int] = None
    ) -> None:
        key = normalize_part_number(part_number)
        if not key:
            return

        query = select(WarehouseItemModel.id).where(
            func.upper(WarehouseItemModel.part_number) == key
        )
        if exclude_id:
            query = query.where(WarehouseItemModel.id != exclude_id)

        if (await self.db.execute(query.limit(1))).first() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"'{part_number}' parça numarası zaten kayıtlı",
            )

    async def create_stock(
        self, data: WarehouseItemCreateSchema, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        await self._ensure_unique_part_number(data.part_number)
        await self._require_territory(data.territory_id)

        item = WarehouseItemModel(
            name=data.name,
            part_number=data.part_number,
            description_tr=data.description_tr,
            description_ru=data.description_ru,
            unit=data.unit,
            territory_id=data.territory_id,
            location=data.location,
            min_quantity=data.min_quantity,
            quantity=0,
            notes=data.notes,
            created_by_id=user_id,
        )
        self.db.add(item)
        try:
            await self.db.flush()
            item_id = item.id
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Stok kartı kaydedilemedi"
            )
        except Exception:
            await self.db.rollback()
            raise

        await self._commit("Stok kartı kaydedilemedi")
        return await self.get_stock(item_id)

    async def update_stock(
        self, item_id: int, data: WarehouseItemUpdateSchema
    ) -> dict[str, Any]:
        item = await self._require(
            WarehouseItemModel, item_id, "Stok kartı bulunamadı"
        )

        changes = data.model_dump(exclude_unset=True)
        if "part_number" in changes:
            await self._ensure_unique_part_number(changes["part_number"], item_id)
        if "territory_id" in changes:
            await self._require_territory(changes["territory_id"])

        for field, value in changes.items():
            setattr(item, field, value)

        await self._commit("Stok kartı güncellenemedi")
        return await self.get_stock(item_id)

    async def delete_stock(self, item_id: int) -> None:
        item = await self._require(
            WarehouseItemModel, item_id, "Stok kartı bulunamadı"
        )

        movement_count = (
            await self.db.execute(
                select(func.count(WarehouseMovementModel.id)).where(
                    WarehouseMovementModel.item_id == item_id
                )
            )
        ).scalar_one()
        if movement_count:
            raise HTTPException(
                status_code=409,
                detail="Hareket görmüş stok kartı silinemez",
            )

        await self.db.delete(item)
        await self._commit("Stok kartı silinemedi")

    # ---------- MOVEMENTS ----------

    def _movement_select(self):
        return (
            select(
                WarehouseMovementModel,
                WarehouseItemModel.name.label("item_name"),
                WarehouseItemModel.part_number.label("item_part_number"),
                WarehouseItemModel.unit.label("unit"),
                AllMachineModel.identification_no.label("identification_no"),
                AllMachineModel.plate_no.label("plate_no"),
                AllMachineModel.vin_no.label("vin_no"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
                SparePartRequestModel.stf_htf_no.label("request_stf_htf_no"),
            )
            .select_from(WarehouseMovementModel)
            .join(
                WarehouseItemModel,
                WarehouseMovementModel.item_id == WarehouseItemModel.id,
            )
            .outerjoin(
                AllMachineModel,
                WarehouseMovementModel.machine_id == AllMachineModel.id,
            )
            .outerjoin(
                UserModel, WarehouseMovementModel.created_by_id == UserModel.id
            )
            .outerjoin(
                SparePartRequestItemModel,
                WarehouseMovementModel.source_request_item_id
                == SparePartRequestItemModel.id,
            )
            .outerjoin(
                SparePartRequestModel,
                SparePartRequestItemModel.request_id == SparePartRequestModel.id,
            )
        )

    def _movement_row_to_item(self, row) -> dict[str, Any]:
        movement: WarehouseMovementModel = row[0]

        return {
            "id": movement.id,
            "item_id": movement.item_id,
            "item_name": row.item_name,
            "item_part_number": row.item_part_number,
            "unit": row.unit,
            "movement_type": movement.movement_type,
            "movement_type_label": movement_type_label(movement.movement_type),
            "quantity": float(movement.quantity or 0),
            "movement_date": movement.movement_date,
            "machine_id": movement.machine_id,
            "identification_no": row.identification_no,
            "plate_no": row.plate_no,
            "vin_no": row.vin_no,
            "machine_label": (
                machine_label(
                    row.identification_no,
                    row.plate_no,
                    row.vin_no,
                    movement.machine_id,
                )
                if movement.machine_id
                else None
            ),
            "document_no": movement.document_no,
            "note": movement.note,
            "source_request_item_id": movement.source_request_item_id,
            "source_request_no": row.request_stf_htf_no,
            "created_by_id": movement.created_by_id,
            "created_by_name": self._creator_name(
                row.creator_firstname, row.creator_lastname
            ),
            "created_at": movement.created_at,
        }

    def _movement_conditions(
        self,
        *,
        search: Optional[str],
        movement_type: Optional[str],
        item_id: Optional[int],
        date_from=None,
        date_to=None,
    ) -> list:
        conditions = []

        pattern = build_search_pattern(search)
        if pattern:
            conditions.append(
                or_(
                    WarehouseItemModel.name.ilike(pattern),
                    WarehouseItemModel.part_number.ilike(pattern),
                    WarehouseMovementModel.document_no.ilike(pattern),
                    WarehouseMovementModel.note.ilike(pattern),
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )
        if movement_type:
            conditions.append(
                WarehouseMovementModel.movement_type == movement_type
            )
        if item_id:
            conditions.append(WarehouseMovementModel.item_id == item_id)
        if date_from:
            conditions.append(WarehouseMovementModel.movement_date >= date_from)
        if date_to:
            conditions.append(WarehouseMovementModel.movement_date <= date_to)

        return conditions

    async def fetch_movements(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        movement_type: Optional[str] = None,
        item_id: Optional[int] = None,
        date_from=None,
        date_to=None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        conditions = self._movement_conditions(
            search=search,
            movement_type=movement_type,
            item_id=item_id,
            date_from=date_from,
            date_to=date_to,
        )

        count_query = (
            select(func.count(WarehouseMovementModel.id))
            .select_from(WarehouseMovementModel)
            .join(
                WarehouseItemModel,
                WarehouseMovementModel.item_id == WarehouseItemModel.id,
            )
            .outerjoin(
                AllMachineModel,
                WarehouseMovementModel.machine_id == AllMachineModel.id,
            )
        )
        rows_query = self._movement_select()
        if conditions:
            count_query = count_query.where(and_(*conditions))
            rows_query = rows_query.where(and_(*conditions))

        total = (await self.db.execute(count_query)).scalar_one()
        result = await self.db.execute(
            rows_query.order_by(
                WarehouseMovementModel.movement_date.desc(),
                WarehouseMovementModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self._movement_row_to_item(row) for row in result.all()],
        }

    async def _movements_by_ids(self, movement_ids: list[int]) -> list[dict]:
        if not movement_ids:
            return []
        result = await self.db.execute(
            self._movement_select()
            .where(WarehouseMovementModel.id.in_(movement_ids))
            .order_by(WarehouseMovementModel.id.asc())
        )
        return [self._movement_row_to_item(row) for row in result.all()]

    async def get_movement(self, movement_id: int) -> dict[str, Any]:
        rows = await self._movements_by_ids([movement_id])
        if not rows:
            raise HTTPException(status_code=404, detail="Hareket bulunamadı")
        return rows[0]

    async def create_movement(
        self, data: WarehouseMovementCreateSchema, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        item = await self._require(
            WarehouseItemModel, data.item_id, "Stok kartı bulunamadı"
        )
        movement_type = validate_movement_type(data.movement_type)

        if data.machine_id is not None:
            await self._require(
                AllMachineModel, data.machine_id, "Makine bulunamadı"
            )
        if data.territory_id is not None:
            await self._require_territory(data.territory_id)

        # Raises 400 when a "cikis" asks for more than the card holds.
        item.quantity = apply_movement(
            item.quantity, movement_type, data.quantity, item.name
        )

        movement = WarehouseMovementModel(
            item_id=item.id,
            movement_type=movement_type,
            quantity=quantize_quantity(data.quantity),
            movement_date=data.movement_date,
            machine_id=data.machine_id,
            territory_id=data.territory_id or item.territory_id,
            document_no=data.document_no,
            note=data.note,
            created_by_id=user_id,
        )
        self.db.add(movement)
        try:
            await self.db.flush()
            movement_id = movement.id
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Hareket kaydedilemedi")
        except Exception:
            await self.db.rollback()
            raise

        await self._commit("Hareket kaydedilemedi")
        return await self.get_movement(movement_id)

    # ---------- RECEIPTS (purchasing -> warehouse) ----------

    @staticmethod
    def _received_exists():
        """``True`` when a spare-part row already produced an in-movement."""

        return (
            select(WarehouseMovementModel.id)
            .where(
                WarehouseMovementModel.source_request_item_id
                == SparePartRequestItemModel.id
            )
            .exists()
        )

    def _pending_select(self):
        return (
            select(
                SparePartRequestItemModel,
                SparePartRequestModel.id.label("request_id"),
                SparePartRequestModel.title.label("request_title"),
                SparePartRequestModel.stf_htf_no.label("stf_htf_no"),
                SparePartRequestModel.request_date.label("request_date"),
                TerritoryModel.name.label("territory_name"),
                SparePartRequestTypeModel.name.label("request_type_name"),
                AllMachineModel.identification_no.label("identification_no"),
                AllMachineModel.plate_no.label("plate_no"),
                AllMachineModel.vin_no.label("vin_no"),
            )
            .select_from(SparePartRequestItemModel)
            .join(
                SparePartRequestModel,
                SparePartRequestItemModel.request_id == SparePartRequestModel.id,
            )
            .join(
                TerritoryModel,
                SparePartRequestModel.territory_id == TerritoryModel.id,
            )
            .join(
                SparePartRequestTypeModel,
                SparePartRequestModel.request_type_id
                == SparePartRequestTypeModel.id,
            )
            .join(
                AllMachineModel,
                SparePartRequestItemModel.machine_id == AllMachineModel.id,
            )
        )

    def _pending_conditions(self, search: Optional[str]) -> list:
        conditions = [
            SparePartRequestModel.status == ARRIVED_STATUS,
            ~self._received_exists(),
        ]

        pattern = build_search_pattern(search)
        if pattern:
            conditions.append(
                or_(
                    SparePartRequestModel.title.ilike(pattern),
                    SparePartRequestModel.stf_htf_no.ilike(pattern),
                    SparePartRequestItemModel.part_number.ilike(pattern),
                    SparePartRequestItemModel.description_tr.ilike(pattern),
                    SparePartRequestItemModel.description_ru.ilike(pattern),
                    SparePartRequestItemModel.garage_request_no.ilike(pattern),
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )

        return conditions

    async def _stock_cards_by_part_number(
        self, part_numbers: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not part_numbers:
            return {}

        result = await self.db.execute(
            select(
                WarehouseItemModel.id,
                WarehouseItemModel.name,
                WarehouseItemModel.part_number,
                WarehouseItemModel.quantity,
            ).where(func.upper(WarehouseItemModel.part_number).in_(part_numbers))
        )

        cards: dict[str, dict[str, Any]] = {}
        for item_id, name, part_number, quantity in result.all():
            key = normalize_part_number(part_number)
            if key:
                cards[key] = {
                    "id": item_id,
                    "name": name,
                    "quantity": float(quantity or 0),
                }
        return cards

    def _pending_row_to_item(
        self, row, cards: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        item: SparePartRequestItemModel = row[0]
        card = cards.get(normalize_part_number(item.part_number))

        return {
            "request_item_id": item.id,
            "request_id": row.request_id,
            "request_title": row.request_title,
            "stf_htf_no": row.stf_htf_no,
            "request_date": row.request_date,
            "territory_name": row.territory_name,
            "request_type_name": row.request_type_name,
            "machine_id": item.machine_id,
            "machine_label": machine_label(
                row.identification_no, row.plate_no, row.vin_no, item.machine_id
            ),
            "garage_request_no": item.garage_request_no,
            "part_number": item.part_number,
            "description_tr": item.description_tr,
            "description_ru": item.description_ru,
            "quantity": float(item.quantity or 0),
            "unit": item.unit,
            "supply_date": item.supply_date,
            "stock_item_id": card["id"] if card else None,
            "stock_item_name": card["name"] if card else None,
            "stock_item_quantity": card["quantity"] if card else 0,
        }

    async def fetch_pending_receipts(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        """Arrived ("geldi") spare-part rows that are not in stock yet."""

        limit, offset = clamp_pagination(limit, offset)
        conditions = self._pending_conditions(search)

        count_query = (
            select(func.count(SparePartRequestItemModel.id))
            .select_from(SparePartRequestItemModel)
            .join(
                SparePartRequestModel,
                SparePartRequestItemModel.request_id == SparePartRequestModel.id,
            )
            .join(
                AllMachineModel,
                SparePartRequestItemModel.machine_id == AllMachineModel.id,
            )
            .where(and_(*conditions))
        )
        total = (await self.db.execute(count_query)).scalar_one()

        result = await self.db.execute(
            self._pending_select()
            .where(and_(*conditions))
            .order_by(
                SparePartRequestModel.request_date.desc(),
                SparePartRequestItemModel.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = result.all()

        part_numbers = {
            normalize_part_number(row[0].part_number) for row in rows
        }
        part_numbers.discard(None)
        cards = await self._stock_cards_by_part_number(part_numbers)

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self._pending_row_to_item(row, cards) for row in rows],
        }

    async def _resolve_stock_card(
        self,
        *,
        part_number: Optional[str],
        name: str,
        unit: str,
        description_tr: Optional[str],
        description_ru: Optional[str],
        territory_id: Optional[int],
        user_id: Optional[int],
    ) -> tuple[WarehouseItemModel, bool]:
        """Find the card a received part belongs to, creating it when new."""

        key = normalize_part_number(part_number)

        if key:
            query = select(WarehouseItemModel).where(
                func.upper(WarehouseItemModel.part_number) == key
            )
        else:
            # Consumables without a part number are matched by their name.
            query = select(WarehouseItemModel).where(
                func.lower(WarehouseItemModel.name) == name.lower(),
                WarehouseItemModel.part_number.is_(None),
            )

        card = (await self.db.execute(query.limit(1))).scalars().first()
        if card is not None:
            return card, False

        card = WarehouseItemModel(
            name=name[:255],
            part_number=part_number,
            description_tr=description_tr,
            description_ru=description_ru,
            unit=unit,
            territory_id=territory_id,
            quantity=0,
            min_quantity=0,
            created_by_id=user_id,
        )
        self.db.add(card)
        await self.db.flush()
        return card, True

    async def receive_items(
        self, data: WarehouseReceiptCreateSchema, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Take arrived spare-part rows into stock as ``giris`` movements."""

        request_item_ids = [line.request_item_id for line in data.items]
        if len(set(request_item_ids)) != len(request_item_ids):
            raise HTTPException(
                status_code=400,
                detail="Aynı talep kalemi birden fazla kez gönderilemez",
            )

        result = await self.db.execute(
            select(SparePartRequestItemModel, SparePartRequestModel)
            .join(
                SparePartRequestModel,
                SparePartRequestItemModel.request_id == SparePartRequestModel.id,
            )
            .where(SparePartRequestItemModel.id.in_(request_item_ids))
        )
        rows = {item.id: (item, request) for item, request in result.all()}

        missing = [
            str(item_id) for item_id in request_item_ids if item_id not in rows
        ]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Talep kalemi bulunamadı: {', '.join(missing)}",
            )

        received = await self.db.execute(
            select(WarehouseMovementModel.source_request_item_id).where(
                WarehouseMovementModel.source_request_item_id.in_(
                    request_item_ids
                )
            )
        )
        already = [
            str(value) for value in received.scalars().all() if value is not None
        ]
        if already:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Bu kalemler daha önce depoya alınmış: "
                    + ", ".join(already)
                ),
            )

        movement_ids: list[int] = []
        created_items = 0

        for line in data.items:
            item, request = rows[line.request_item_id]

            if request.status != ARRIVED_STATUS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{request.stf_htf_no}' talebi 'Geldi' durumunda "
                        "değil; önce satın alma tarafından işaretlenmeli"
                    ),
                )

            quantity = line.quantity or quantize_quantity(item.quantity)
            name = (
                item.description_tr
                or item.description_ru
                or item.part_number
                or f"Kalem #{item.id}"
            ).strip()

            card, created = await self._resolve_stock_card(
                part_number=item.part_number,
                name=name,
                unit=item.unit,
                description_tr=item.description_tr,
                description_ru=item.description_ru,
                territory_id=request.territory_id,
                user_id=user_id,
            )
            created_items += 1 if created else 0

            card.quantity = apply_movement(
                card.quantity, MOVEMENT_IN, quantity, card.name
            )

            movement = WarehouseMovementModel(
                item_id=card.id,
                movement_type=MOVEMENT_IN,
                quantity=quantize_quantity(quantity),
                movement_date=data.movement_date,
                machine_id=item.machine_id,
                territory_id=request.territory_id,
                document_no=request.stf_htf_no,
                note=data.note or request.title,
                source_request_item_id=item.id,
                created_by_id=user_id,
            )
            self.db.add(movement)
            await self.db.flush()
            movement_ids.append(movement.id)

        await self._commit("Talep kalemleri depoya alınamadı")

        return {
            "received": len(data.items),
            "created_items": created_items,
            "movements": await self._movements_by_ids(movement_ids),
        }

    # ---------- SUMMARY ----------

    async def summary(self) -> dict[str, Any]:
        today = date.today()
        month_start = today.replace(day=1)

        stock_items = (
            await self.db.execute(
                select(func.count()).select_from(WarehouseItemModel)
            )
        ).scalar_one()

        critical_items = (
            await self.db.execute(
                select(func.count())
                .select_from(WarehouseItemModel)
                .where(
                    WarehouseItemModel.quantity
                    <= WarehouseItemModel.min_quantity
                )
            )
        ).scalar_one()

        total_quantity = (
            await self.db.execute(
                select(func.coalesce(func.sum(WarehouseItemModel.quantity), 0))
            )
        ).scalar_one()

        pending_receipts = (
            await self.db.execute(
                select(func.count(SparePartRequestItemModel.id))
                .select_from(SparePartRequestItemModel)
                .join(
                    SparePartRequestModel,
                    SparePartRequestItemModel.request_id
                    == SparePartRequestModel.id,
                )
                .where(
                    SparePartRequestModel.status == ARRIVED_STATUS,
                    ~self._received_exists(),
                )
            )
        ).scalar_one()

        def month_total(movement_type: str):
            return select(
                func.coalesce(func.sum(WarehouseMovementModel.quantity), 0)
            ).where(
                WarehouseMovementModel.movement_type == movement_type,
                WarehouseMovementModel.movement_date >= month_start,
                WarehouseMovementModel.movement_date <= today,
            )

        month_in = (await self.db.execute(month_total(MOVEMENT_IN))).scalar_one()
        month_out = (
            await self.db.execute(month_total(MOVEMENT_OUT))
        ).scalar_one()

        return {
            "stock_items": stock_items,
            "critical_items": critical_items,
            "pending_receipts": pending_receipts,
            "total_quantity": float(total_quantity or 0),
            "month_in_quantity": float(month_in or 0),
            "month_out_quantity": float(month_out or 0),
        }
