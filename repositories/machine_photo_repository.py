# repositories/machine_photo_repository.py
"""Database side of machine photos (S3 upload/delete lives in the router)."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models.machine_photo_model import MachinePhotoModel
from models.machines_model import AllMachineModel


class MachinePhotoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Köməkçi ----------
    async def _ensure_machine(self, machine_id: int) -> None:
        result = await self.db.execute(
            select(AllMachineModel.id).where(AllMachineModel.id == machine_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

    async def _clear_primary(self, machine_id: int) -> None:
        """Demote the current primary photo *before* inserting/promoting another.

        The partial unique index (one primary per machine) is checked on flush,
        so this must run first inside the same transaction.
        """

        await self.db.execute(
            update(MachinePhotoModel)
            .where(
                MachinePhotoModel.machine_id == machine_id,
                MachinePhotoModel.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
        await self.db.flush()

    # ---------- READ ----------
    async def fetch_machine_photos(self, machine_id: int) -> list[MachinePhotoModel]:
        await self._ensure_machine(machine_id)

        result = await self.db.execute(
            select(MachinePhotoModel)
            .where(MachinePhotoModel.machine_id == machine_id)
            .order_by(
                MachinePhotoModel.is_primary.desc(),
                MachinePhotoModel.id,
            )
        )
        return list(result.scalars().all())

    async def fetch_by_id(self, photo_id: int) -> MachinePhotoModel:
        result = await self.db.execute(
            select(MachinePhotoModel).where(MachinePhotoModel.id == photo_id)
        )
        photo = result.scalar_one_or_none()
        if photo is None:
            raise HTTPException(status_code=404, detail="Fotoğraf bulunamadı")
        return photo

    async def keys_for_machine(self, machine_id: int) -> list[str]:
        result = await self.db.execute(
            select(MachinePhotoModel.object_key).where(
                MachinePhotoModel.machine_id == machine_id
            )
        )
        return list(result.scalars().all())

    # ---------- CREATE ----------
    async def create(
        self,
        machine_id: int,
        *,
        object_key: str,
        original_filename: str | None,
        content_type: str | None,
        size_bytes: int | None,
        uploaded_by_id: int | None = None,
        is_primary: bool = False,
    ) -> MachinePhotoModel:
        await self._ensure_machine(machine_id)

        existing_count = await self.db.scalar(
            select(func.count(MachinePhotoModel.id)).where(
                MachinePhotoModel.machine_id == machine_id
            )
        )
        # The very first photo of a machine is always the primary one.
        make_primary = is_primary or not existing_count

        if make_primary:
            await self._clear_primary(machine_id)

        photo = MachinePhotoModel(
            machine_id=machine_id,
            object_key=object_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by_id=uploaded_by_id,
            is_primary=make_primary,
        )
        self.db.add(photo)

        try:
            await self.db.commit()
            await self.db.refresh(photo)
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Fotoğraf kaydedilemedi, lütfen tekrar deneyin",
            )
        except Exception:
            await self.db.rollback()
            raise

        return photo

    # ---------- UPDATE ----------
    async def set_primary(self, photo_id: int) -> MachinePhotoModel:
        photo = await self.fetch_by_id(photo_id)

        if not photo.is_primary:
            await self._clear_primary(photo.machine_id)
            photo.is_primary = True

            try:
                await self.db.commit()
                await self.db.refresh(photo)
            except IntegrityError:
                await self.db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Ana fotoğraf güncellenemedi, lütfen tekrar deneyin",
                )
            except Exception:
                await self.db.rollback()
                raise

        return photo

    # ---------- DELETE ----------
    async def delete(self, photo_id: int) -> str:
        """Delete the row and return the S3 object key for cleanup."""

        photo = await self.fetch_by_id(photo_id)
        object_key = photo.object_key
        machine_id = photo.machine_id
        was_primary = photo.is_primary

        try:
            await self.db.delete(photo)
            await self.db.flush()

            # Promote the oldest remaining photo so a machine keeps a cover.
            if was_primary:
                next_photo_id = await self.db.scalar(
                    select(MachinePhotoModel.id)
                    .where(MachinePhotoModel.machine_id == machine_id)
                    .order_by(MachinePhotoModel.id)
                    .limit(1)
                )
                if next_photo_id is not None:
                    await self.db.execute(
                        update(MachinePhotoModel)
                        .where(MachinePhotoModel.id == next_photo_id)
                        .values(is_primary=True)
                    )

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return object_key
