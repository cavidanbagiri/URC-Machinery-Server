# repositories/user_avatar_repository.py
"""Database side of a signed-in user's profile photo.

The bytes live in S3-compatible storage (see services/storage_service.py);
PostgreSQL only keeps the object key, reached through
``users.image_id -> images.url``. The router uploads/deletes the objects, this
repository swaps the pointers.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_model import ImageModel, UserModel


class UserAvatarRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def replace(self, user_id: int, object_key: str) -> str:
        """Point the user at ``object_key`` and return the previous URL.

        The ``images`` row is reused when the user already had a photo, so image
        ids stay stable. The returned value is the superseded ``images.url``
        (``""`` when there was none) — the caller deletes that object, and only
        when it actually is an object key rather than an external URL.
        """

        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

        previous_url = ""

        image = await self.db.get(ImageModel, user.image_id) if user.image_id else None
        if image is not None:
            previous_url = image.url or ""
            image.url = object_key
        else:
            image = ImageModel(url=object_key)
            self.db.add(image)

        try:
            await self.db.flush()
            user.image_id = image.id
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return previous_url
