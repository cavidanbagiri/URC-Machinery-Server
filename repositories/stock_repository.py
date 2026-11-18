# repositories/stock_repository.py
"""Basit stok modülünün veri erişimi.

Eski Ambar modülünden bağımsızdır: kart üzerindeki ``quantity`` tek doğruluk
kaynağıdır.  Her "Sahaya Çıkar" işlemi ``stock_issues`` tablosuna bir satır
yazar ve miktarı düşer; kayıt silinirse miktar geri eklenir.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.machines_model import AllMachineModel
from models.stock_model import StockIssueModel, StockModel, quantize_quantity
from models.user_model import UserModel
from schemas.stock_schemas import (
    StockIssueCreateSchema,
    StockItemCreateSchema,
    StockItemUpdateSchema,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


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


def quantity_text(value) -> str:
    """``Decimal('2.000')`` -> ``"2"``, ``Decimal('2.500')`` -> ``"2.5"``."""

    return f"{quantize_quantity(value).normalize():f}"


def apply_stock_out(
    current_quantity,
    quantity,
    item_name: Optional[str] = None,
) -> Decimal:
    """Çıkıştan sonraki bakiyeyi döndür; stok yetmiyorsa 400 fırlat."""

    current = quantize_quantity(current_quantity)
    amount = quantize_quantity(quantity)

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Miktar sıfırdan büyük olmalı",
        )

    if amount > current:
        label = item_name or "stok kalemi"
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
    """Makine kolonunda gösterilecek etiket; yoksa veritabanı id'si."""

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

class StockRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- SHARED HELPERS ----------

    @staticmethod
    def _creator_name(
        firstname: Optional[str], lastname: Optional[str]
    ) -> Optional[str]:
        name = " ".join(part for part in (firstname, lastname) if part).strip()
        return name or None

    async def _require_item(self, item_id: int) -> StockModel:
        item = await self.db.get(StockModel, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Stok kalemi bulunamadı")
        return item

    async def _commit(self, message: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail=message) from exc
        except Exception:
            await self.db.rollback()
            raise

    # ---------- STOCK ITEMS ----------

    @staticmethod
    def _item_select():
        issue_counts = (
            select(
                StockIssueModel.stock_item_id.label("stock_item_id"),
                func.count(StockIssueModel.id).label("issue_count"),
            )
            .group_by(StockIssueModel.stock_item_id)
            .subquery()
        )

        return (
            select(
                StockModel,
                func.coalesce(issue_counts.c.issue_count, 0).label(
                    "issue_count"
                ),
            )
            .select_from(StockModel)
            .outerjoin(
                issue_counts,
                StockModel.id == issue_counts.c.stock_item_id,
            )
        )

    @staticmethod
    def _item_to_dict(item: StockModel, issue_count: int = 0) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "unit": item.unit,
            "quantity": float(item.quantity or 0),
            "notes": item.notes,
            "issue_count": int(issue_count or 0),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    async def fetch_items(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)

        conditions = []
        pattern = build_search_pattern(search)
        if pattern:
            conditions.append(
                or_(
                    StockModel.name.ilike(pattern),
                    StockModel.notes.ilike(pattern),
                )
            )

        count_query = select(func.count(StockModel.id))
        if conditions:
            count_query = count_query.where(*conditions)

        total = int((await self.db.execute(count_query)).scalar() or 0)

        rows_query = self._item_select()
        if conditions:
            rows_query = rows_query.where(*conditions)

        rows_query = (
            rows_query.order_by(StockModel.name.asc(), StockModel.id.asc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(rows_query)
        items = [
            self._item_to_dict(row[0], row.issue_count)
            for row in result.all()
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def get_item(self, item_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._item_select().where(StockModel.id == item_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Stok kalemi bulunamadı")
        return self._item_to_dict(row[0], row.issue_count)

    async def create_item(
        self,
        data: StockItemCreateSchema,
        user_id: int,
    ) -> dict[str, Any]:
        item = StockModel(
            name=data.name,
            unit=data.unit,
            quantity=quantize_quantity(data.quantity),
            notes=data.notes,
            created_by_id=user_id,
        )
        self.db.add(item)
        await self._commit("Stok kalemi kaydedilemedi")
        await self.db.refresh(item)
        return self._item_to_dict(item, 0)

    async def update_item(
        self,
        item_id: int,
        data: StockItemUpdateSchema,
    ) -> dict[str, Any]:
        item = await self._require_item(item_id)
        payload = data.model_dump(exclude_unset=True)

        if payload.get("name") is not None:
            item.name = payload["name"]
        if payload.get("unit") is not None:
            item.unit = payload["unit"]
        if payload.get("quantity") is not None:
            item.quantity = quantize_quantity(payload["quantity"])
        if "notes" in payload:
            item.notes = payload["notes"]

        await self._commit("Stok kalemi güncellenemedi")
        await self.db.refresh(item)
        return await self.get_item(item.id)

    async def delete_item(self, item_id: int) -> None:
        item = await self._require_item(item_id)
        await self.db.delete(item)
        await self._commit("Stok kalemi silinemedi")

    # ---------- ISSUES (SAHAYA ÇIKANLAR) ----------

    @staticmethod
    def _issue_select():
        return (
            select(
                StockIssueModel,
                StockModel.name.label("item_name"),
                StockModel.unit.label("unit"),
                AllMachineModel.identification_no.label("identification_no"),
                AllMachineModel.plate_no.label("plate_no"),
                AllMachineModel.vin_no.label("vin_no"),
                UserModel.firstname.label("creator_firstname"),
                UserModel.lastname.label("creator_lastname"),
            )
            .select_from(StockIssueModel)
            .join(StockModel, StockIssueModel.stock_item_id == StockModel.id)
            .outerjoin(
                AllMachineModel,
                StockIssueModel.machine_id == AllMachineModel.id,
            )
            .outerjoin(UserModel, StockIssueModel.created_by_id == UserModel.id)
        )

    def _issue_to_dict(self, row) -> dict[str, Any]:
        issue: StockIssueModel = row[0]
        return {
            "id": issue.id,
            "stock_item_id": issue.stock_item_id,
            "item_name": row.item_name,
            "unit": row.unit,
            "quantity": float(issue.quantity or 0),
            "issue_date": issue.issue_date,
            "machine_id": issue.machine_id,
            "identification_no": row.identification_no,
            "plate_no": row.plate_no,
            "vin_no": row.vin_no,
            "machine_label": (
                machine_label(
                    row.identification_no,
                    row.plate_no,
                    row.vin_no,
                    issue.machine_id,
                )
                if issue.machine_id
                else None
            ),
            "given_to": issue.given_to,
            "note": issue.note,
            "created_by_id": issue.created_by_id,
            "created_by_name": self._creator_name(
                row.creator_firstname,
                row.creator_lastname,
            ),
            "created_at": issue.created_at,
        }

    async def _get_issue_row(self, issue_id: int):
        result = await self.db.execute(
            self._issue_select().where(StockIssueModel.id == issue_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Stok çıkışı bulunamadı")
        return row

    def _issue_conditions(
        self,
        *,
        search: Optional[str],
        stock_item_id: Optional[int],
        machine_id: Optional[int],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list:
        conditions = []

        pattern = build_search_pattern(search)
        if pattern:
            conditions.append(
                or_(
                    StockModel.name.ilike(pattern),
                    StockIssueModel.given_to.ilike(pattern),
                    StockIssueModel.note.ilike(pattern),
                    AllMachineModel.identification_no.ilike(pattern),
                    AllMachineModel.plate_no.ilike(pattern),
                    AllMachineModel.vin_no.ilike(pattern),
                )
            )
        if stock_item_id:
            conditions.append(StockIssueModel.stock_item_id == stock_item_id)
        if machine_id:
            conditions.append(StockIssueModel.machine_id == machine_id)
        if date_from:
            conditions.append(StockIssueModel.issue_date >= date_from)
        if date_to:
            conditions.append(StockIssueModel.issue_date <= date_to)

        return conditions

    async def fetch_issues(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        stock_item_id: Optional[int] = None,
        machine_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)

        conditions = self._issue_conditions(
            search=search,
            stock_item_id=stock_item_id,
            machine_id=machine_id,
            date_from=date_from,
            date_to=date_to,
        )

        count_query = (
            select(func.count(StockIssueModel.id))
            .select_from(StockIssueModel)
            .join(StockModel, StockIssueModel.stock_item_id == StockModel.id)
            .outerjoin(
                AllMachineModel,
                StockIssueModel.machine_id == AllMachineModel.id,
            )
        )
        if conditions:
            count_query = count_query.where(*conditions)

        total = int((await self.db.execute(count_query)).scalar() or 0)

        rows_query = self._issue_select()
        if conditions:
            rows_query = rows_query.where(*conditions)

        rows_query = (
            rows_query.order_by(
                StockIssueModel.issue_date.desc(),
                StockIssueModel.created_at.desc(),
                StockIssueModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(rows_query)
        items = [self._issue_to_dict(row) for row in result.all()]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def create_issue(
        self,
        data: StockIssueCreateSchema,
        user_id: int,
    ) -> dict[str, Any]:
        item = await self._require_item(data.stock_item_id)

        if data.machine_id:
            machine = await self.db.get(AllMachineModel, data.machine_id)
            if machine is None:
                raise HTTPException(status_code=404, detail="Makine bulunamadı")

        amount = quantize_quantity(data.quantity)
        item.quantity = apply_stock_out(item.quantity, amount, item.name)

        issue = StockIssueModel(
            stock_item_id=item.id,
            quantity=amount,
            issue_date=data.issue_date,
            machine_id=data.machine_id,
            given_to=data.given_to,
            note=data.note,
            created_by_id=user_id,
        )
        self.db.add(issue)

        await self._commit("Stok çıkışı kaydedilemedi")
        await self.db.refresh(issue)

        return self._issue_to_dict(await self._get_issue_row(issue.id))

    async def delete_issue(self, issue_id: int) -> dict[str, Any]:
        """Yanlış girilen çıkışı geri al: miktarı stoğa ekle."""

        issue = await self.db.get(StockIssueModel, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Stok çıkışı bulunamadı")

        item = await self._require_item(issue.stock_item_id)
        restored = quantize_quantity(issue.quantity)
        item.quantity = quantize_quantity((item.quantity or 0) + restored)

        await self.db.delete(issue)
        await self._commit("Stok çıkışı silinemedi")

        return {
            "stock_item_id": item.id,
            "quantity": float(restored),
            "new_quantity": float(item.quantity),
        }

    # ---------- SUMMARY ----------

    async def summary(self) -> dict[str, Any]:
        month_start = date.today().replace(day=1)

        item_count = int(
            (await self.db.execute(select(func.count(StockModel.id)))).scalar()
            or 0
        )
        total_quantity = (
            await self.db.execute(
                select(func.coalesce(func.sum(StockModel.quantity), 0))
            )
        ).scalar() or 0
        out_of_stock_items = int(
            (
                await self.db.execute(
                    select(func.count(StockModel.id)).where(
                        StockModel.quantity <= 0
                    )
                )
            ).scalar()
            or 0
        )

        month_row = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(StockIssueModel.quantity), 0
                    ).label("quantity"),
                    func.count(StockIssueModel.id).label("count"),
                ).where(StockIssueModel.issue_date >= month_start)
            )
        ).one()

        return {
            "item_count": item_count,
            "total_quantity": float(total_quantity or 0),
            "out_of_stock_items": out_of_stock_items,
            "month_issue_quantity": float(month_row.quantity or 0),
            "month_issue_count": int(month_row.count or 0),
        }
