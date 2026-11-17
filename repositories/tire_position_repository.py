# repositories/tire_position_repository.py
"""Database access for the Settings-managed tire position lookup.

``tire_changes.position`` stays free text: a crane and a truck need different
names, the form lets the operator type a custom value, and historical rows must
remain readable even if a position is removed from the list. The lookup only
feeds the suggestions (form datalist, column filter).

Renaming a position rewrites the stored text of the existing changes, otherwise
one physical wheel would be split between the old and the new label in the
"eski kayıtlar" history. Deleting a position that is still used is rejected,
exactly like the other Settings lookups (repair type, garage service).
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.tire_model import TireChangeModel, TirePositionModel
from schemas.tire_schemas import TirePositionCreateSchema


class TirePositionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    async def _ensure_name_free(
        self, name: str, exclude_id: Optional[int] = None
    ) -> None:
        """Reject near-duplicates (``sol ön`` vs ``Sol Ön``) with a 409."""

        query = select(TirePositionModel.id).where(
            func.lower(TirePositionModel.name) == name.lower()
        )
        if exclude_id is not None:
            query = query.where(TirePositionModel.id != exclude_id)

        existing = await self.db.execute(query.limit(1))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Bu ada sahip lastik konumu zaten mevcut",
            )

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Bu ada sahip lastik konumu zaten mevcut",
            ) from None

    # ---------- READ ----------

    async def fetch_all(self) -> list[TirePositionModel]:
        result = await self.db.execute(
            select(TirePositionModel).order_by(TirePositionModel.id)
        )
        return list(result.scalars().all())

    async def fetch_by_id(self, position_id: int) -> TirePositionModel:
        result = await self.db.execute(
            select(TirePositionModel).where(TirePositionModel.id == position_id)
        )
        position = result.scalar_one_or_none()
        if position is None:
            raise HTTPException(
                status_code=404, detail="Lastik konumu bulunamadı"
            )
        return position

    # ---------- WRITE ----------

    async def create(self, data: TirePositionCreateSchema) -> TirePositionModel:
        await self._ensure_name_free(data.name)

        position = TirePositionModel(name=data.name)
        self.db.add(position)
        await self._commit()
        await self.db.refresh(position)
        return position

    async def update(
        self, position_id: int, data: TirePositionCreateSchema
    ) -> TirePositionModel:
        position = await self.fetch_by_id(position_id)
        if position.name == data.name:
            return position

        await self._ensure_name_free(data.name, exclude_id=position_id)

        old_name = position.name
        position.name = data.name
        # The record stores text, not an FK, so carry the history along.
        await self.db.execute(
            update(TireChangeModel)
            .where(func.lower(TireChangeModel.position) == old_name.lower())
            .values(position=data.name)
        )

        await self._commit()
        await self.db.refresh(position)
        return position

    async def delete(self, position_id: int) -> None:
        position = await self.fetch_by_id(position_id)

        used = await self.db.execute(
            select(TireChangeModel.id)
            .where(func.lower(TireChangeModel.position) == position.name.lower())
            .limit(1)
        )
        if used.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Bu lastik konumu kayıtlarda kullanıldığı için silinemez"
                ),
            )

        await self.db.delete(position)
        await self._commit()


__all__ = ["TirePositionRepository"]
