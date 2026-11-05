# repositories/forum_repository.py
"""Database access for the forum (topics, comments and topic photos)."""

from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.permissions import WRITE_PERMISSION_VALUES, get_permission_value
from models.forum_model import (
    MAX_PHOTOS_PER_TOPIC,
    MAX_PHOTO_BYTES,
    ForumCommentModel,
    ForumTopicModel,
    ForumTopicPhotoModel,
)
from models.machines_model import AllMachineModel, CarStatusModel
from models.user_model import UserModel
from schemas.forum_schemas import (
    MAX_MACHINE_OPTIONS,
    ForumCommentCreateSchema,
    ForumResolveSchema,
    ForumTopicCreateSchema,
)
from services.storage_service import resolve_content_type

DEFAULT_LIMIT = 10
MAX_LIMIT = 50

#: ``status`` query values: everything, only open or only resolved topics.
STATUS_FILTERS = ("all", "open", "resolved")

_FALLBACK_PHOTO_NAME = "foto.jpg"

#: Magic bytes per accepted image type; the declared type is client supplied and
#: therefore not trusted on its own.
_IMAGE_SIGNATURES = (
    ("image/jpeg", (b"\xff\xd8\xff",)),
    ("image/png", (b"\x89PNG\r\n\x1a\n",)),
)


# =========================================================
# PURE HELPERS (unit tested without a database)
# =========================================================

def clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    """Keep client supplied paging inside the API limits."""

    limit = DEFAULT_LIMIT if limit < 1 else min(limit, MAX_LIMIT)
    offset = max(offset, 0)
    return limit, offset


def normalize_status_filter(value: Optional[str]) -> str:
    """Map the ``status`` query parameter to ``all`` / ``open`` / ``resolved``.

    Unknown values fall back to ``all`` instead of returning a 422: the filter is
    a convenience for the UI, not a contract.
    """

    candidate = (value or "").strip().lower()
    return candidate if candidate in STATUS_FILTERS else "all"


def sanitize_file_name(file_name: Optional[str]) -> str:
    """Take the base name only: never trust a path sent by the browser."""

    name = (file_name or "").replace("\\", "/").split("/")[-1].strip()
    name = name[:255].strip()
    return name or _FALLBACK_PHOTO_NAME


def has_image_signature(content_type: str, data: bytes) -> bool:
    """True when the bytes really look like the declared image type."""

    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"

    for declared, signatures in _IMAGE_SIGNATURES:
        if declared == content_type:
            return any(data.startswith(signature) for signature in signatures)
    return False


def validate_photo(
    file_name: Optional[str], content_type: Optional[str], data: bytes
) -> dict[str, Any]:
    """Validate an uploaded photo; raises ``ValueError`` with a Turkish text."""

    if not data:
        raise ValueError("Boş dosya yüklenemez")

    if len(data) > MAX_PHOTO_BYTES:
        limit_mb = MAX_PHOTO_BYTES // (1024 * 1024)
        raise ValueError(f"Fotoğraf boyutu en fazla {limit_mb} MB olabilir")

    resolved_name = sanitize_file_name(file_name)

    try:
        resolved_type = resolve_content_type(file_name or resolved_name, content_type)
    except ValueError as exc:
        raise ValueError("Sadece JPEG, PNG veya WEBP fotoğraf yükleyebilirsiniz") from exc

    if not has_image_signature(resolved_type, data):
        raise ValueError("Dosya geçerli bir fotoğraf değil")

    return {
        "file_name": resolved_name,
        "content_type": resolved_type,
        "file_size": len(data),
    }


def inline_disposition(file_name: str) -> str:
    """``Content-Disposition`` for an inline photo with a UTF-8 safe name."""

    name = sanitize_file_name(file_name)
    ascii_name = (
        name.encode("ascii", "ignore").decode("ascii") or _FALLBACK_PHOTO_NAME
    )
    ascii_name = ascii_name.replace('"', "_")
    return f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def can_manage_topic(user: UserModel, topic_created_by_id: Optional[int]) -> bool:
    """The author owns the topic; otherwise write permission is required."""

    if user is None:
        return False
    if topic_created_by_id is not None and user.id == topic_created_by_id:
        return True
    return get_permission_value(user.status_id) in WRITE_PERMISSION_VALUES


def ensure_can_manage_topic(
    user: UserModel, topic_created_by_id: Optional[int]
) -> None:
    if not can_manage_topic(user, topic_created_by_id):
        raise HTTPException(
            status_code=403,
            detail="Bu konuyu yalnızca konuyu açan kişi kapatabilir",
        )


# =========================================================
# REPOSITORY
# =========================================================

class ForumRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- HELPERS ----------

    def _base_select(self):
        return (
            select(
                ForumTopicModel,
                AllMachineModel.identification_no,
                AllMachineModel.plate_no,
                UserModel.firstname.label("author_firstname"),
                UserModel.lastname.label("author_lastname"),
                UserModel.position.label("author_position"),
            )
            .select_from(ForumTopicModel)
            .outerjoin(AllMachineModel, ForumTopicModel.machine_id == AllMachineModel.id)
            .outerjoin(UserModel, ForumTopicModel.created_by_id == UserModel.id)
        )

    def _row_to_item(
        self,
        row,
        photos: Optional[list[dict[str, Any]]] = None,
        comments: Optional[list[dict[str, Any]]] = None,
        resolved_by_name: Optional[str] = None,
    ) -> dict[str, Any]:
        topic: ForumTopicModel = row[0]

        author_name = " ".join(
            part for part in (row.author_firstname, row.author_lastname) if part
        ).strip()

        machine_label = (
            row.identification_no
            or row.plate_no
            or (f"Makine #{topic.machine_id}" if topic.machine_id else None)
        )

        return {
            "id": topic.id,
            "title": topic.title,
            "body": topic.body,
            "machine_id": topic.machine_id,
            "machine_label": machine_label,
            "identification_no": row.identification_no,
            "plate_no": row.plate_no,
            "author_id": topic.created_by_id,
            "author_name": author_name or None,
            "author_position": (row.author_position or None),
            "is_resolved": bool(topic.is_resolved),
            "resolved_at": topic.resolved_at,
            "resolved_by_id": topic.resolved_by_id,
            "resolved_by_name": resolved_by_name,
            "resolution_note": topic.resolution_note,
            "created_at": topic.created_at,
            "updated_at": topic.updated_at,
            "comments_count": len(comments or []),
            "photos": photos or [],
            "comments": comments or [],
        }

    async def _photos_for(
        self, topic_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Photo metadata only: the image bytes never enter a list query."""

        grouped: dict[int, list[dict[str, Any]]] = {
            topic_id: [] for topic_id in topic_ids
        }
        if not topic_ids:
            return grouped

        result = await self.db.execute(
            select(
                ForumTopicPhotoModel.id,
                ForumTopicPhotoModel.topic_id,
                ForumTopicPhotoModel.file_name,
                ForumTopicPhotoModel.content_type,
                ForumTopicPhotoModel.file_size,
                ForumTopicPhotoModel.uploaded_by_id,
                UserModel.firstname,
                UserModel.lastname,
                ForumTopicPhotoModel.created_at,
            )
            .outerjoin(
                UserModel,
                ForumTopicPhotoModel.uploaded_by_id == UserModel.id,
            )
            .where(ForumTopicPhotoModel.topic_id.in_(topic_ids))
            .order_by(
                ForumTopicPhotoModel.created_at.asc(),
                ForumTopicPhotoModel.id.asc(),
            )
        )
        for (
            photo_id,
            topic_id,
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
            grouped.setdefault(topic_id, []).append(
                {
                    "id": photo_id,
                    "topic_id": topic_id,
                    "file_name": file_name,
                    "content_type": content_type or "image/jpeg",
                    "file_size": file_size or 0,
                    "uploaded_by_id": uploaded_by_id,
                    "uploaded_by_name": uploader_name or None,
                    "created_at": created_at,
                }
            )
        return grouped

    async def _comments_for(
        self, topic_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {
            topic_id: [] for topic_id in topic_ids
        }
        if not topic_ids:
            return grouped

        result = await self.db.execute(
            select(
                ForumCommentModel.id,
                ForumCommentModel.topic_id,
                ForumCommentModel.body,
                ForumCommentModel.created_by_id,
                UserModel.firstname,
                UserModel.lastname,
                UserModel.position,
                ForumCommentModel.created_at,
                ForumCommentModel.updated_at,
            )
            .outerjoin(UserModel, ForumCommentModel.created_by_id == UserModel.id)
            .where(ForumCommentModel.topic_id.in_(topic_ids))
            .order_by(
                ForumCommentModel.created_at.asc(),
                ForumCommentModel.id.asc(),
            )
        )
        for (
            comment_id,
            topic_id,
            body,
            author_id,
            firstname,
            lastname,
            position,
            created_at,
            updated_at,
        ) in result.all():
            author_name = " ".join(
                part for part in (firstname, lastname) if part
            ).strip()
            grouped.setdefault(topic_id, []).append(
                {
                    "id": comment_id,
                    "topic_id": topic_id,
                    "body": body,
                    "author_id": author_id,
                    "author_name": author_name or None,
                    "author_position": position or None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return grouped

    def _list_conditions(
        self,
        *,
        search: Optional[str],
        status: str,
        mine: bool,
        user_id: Optional[int],
        machine_id: Optional[int],
    ) -> list:
        conditions = []

        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            conditions.append(
                or_(
                    ForumTopicModel.title.ilike(pattern),
                    ForumTopicModel.body.ilike(pattern),
                )
            )

        if status == "open":
            conditions.append(ForumTopicModel.is_resolved.is_(False))
        elif status == "resolved":
            conditions.append(ForumTopicModel.is_resolved.is_(True))

        if mine and user_id is not None:
            conditions.append(ForumTopicModel.created_by_id == user_id)

        if machine_id:
            conditions.append(ForumTopicModel.machine_id == machine_id)

        return conditions

    # ---------- READ ----------

    async def fetch_paginated(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
        mine: bool = False,
        user_id: Optional[int] = None,
        machine_id: Optional[int] = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_pagination(limit, offset)
        status_filter = normalize_status_filter(status)
        conditions = self._list_conditions(
            search=search,
            status=status_filter,
            mine=mine,
            user_id=user_id,
            machine_id=machine_id,
        )

        total = (
            await self.db.execute(
                select(func.count())
                .select_from(ForumTopicModel)
                .where(*conditions)
            )
        ).scalar() or 0

        result = await self.db.execute(
            self._base_select()
            .where(*conditions)
            # Open topics first, newest on top inside each group.
            .order_by(
                ForumTopicModel.is_resolved.asc(),
                ForumTopicModel.created_at.desc(),
                ForumTopicModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = result.all()

        topic_ids = [row[0].id for row in rows]
        photos = await self._photos_for(topic_ids)
        comments = await self._comments_for(topic_ids)
        resolvers = await self._resolver_names(
            [row[0].resolved_by_id for row in rows]
        )

        items = [
            self._row_to_item(
                row,
                photos.get(row[0].id, []),
                comments.get(row[0].id, []),
                resolvers.get(row[0].resolved_by_id),
            )
            for row in rows
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def _resolver_names(
        self, user_ids: list[Optional[int]]
    ) -> dict[int, str]:
        """Resolve the "who closed the topic" names in one query."""

        wanted = sorted({user_id for user_id in user_ids if user_id})
        if not wanted:
            return {}

        result = await self.db.execute(
            select(
                UserModel.id,
                UserModel.firstname,
                UserModel.lastname,
            ).where(UserModel.id.in_(wanted))
        )
        names: dict[int, str] = {}
        for user_id, firstname, lastname in result.all():
            name = " ".join(
                part for part in (firstname, lastname) if part
            ).strip()
            if name:
                names[user_id] = name
        return names

    async def _get_topic(self, topic_id: int) -> ForumTopicModel:
        topic = await self.db.get(ForumTopicModel, topic_id)
        if topic is None:
            raise HTTPException(status_code=404, detail="Forum konusu bulunamadı")
        return topic

    async def _get_item(self, topic_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            self._base_select().where(ForumTopicModel.id == topic_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Forum konusu bulunamadı")

        photos = await self._photos_for([topic_id])
        comments = await self._comments_for([topic_id])
        resolvers = await self._resolver_names([row[0].resolved_by_id])
        return self._row_to_item(
            row,
            photos.get(topic_id, []),
            comments.get(topic_id, []),
            resolvers.get(row[0].resolved_by_id),
        )

    async def fetch_topic(self, topic_id: int) -> dict[str, Any]:
        """One topic with its photos and comments (detail view)."""

        return await self._get_item(topic_id)

    async def get_photo(
        self, topic_id: int, photo_id: int
    ) -> ForumTopicPhotoModel:
        photo = await self.db.get(ForumTopicPhotoModel, photo_id)
        if photo is None or photo.topic_id != topic_id:
            raise HTTPException(status_code=404, detail="Fotoğraf bulunamadı")
        return photo

    async def search_machine_options(
        self, *, search: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, MAX_MACHINE_OPTIONS))
        query = (
            select(
                AllMachineModel.id,
                AllMachineModel.identification_no,
                AllMachineModel.plate_no,
                AllMachineModel.vin_no,
                CarStatusModel.name.label("status_name"),
            )
            .select_from(AllMachineModel)
            .outerjoin(CarStatusModel, AllMachineModel.status_id == CarStatusModel.id)
        )

        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
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
                "id": row.id,
                "identification_no": row.identification_no,
                "plate_no": row.plate_no,
                "vin_no": row.vin_no,
                "status_name": row.status_name,
            }
            for row in result.all()
        ]

    # ---------- WRITE ----------

    async def _require_machine(self, machine_id: Optional[int]) -> None:
        if machine_id is None:
            return
        machine = await self.db.get(AllMachineModel, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail="Makine bulunamadı")

    async def _commit(self, error_detail: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail=error_detail) from exc
        except Exception:
            await self.db.rollback()
            raise

    async def create_topic(
        self, data: ForumTopicCreateSchema, user_id: Optional[int]
    ) -> dict[str, Any]:
        await self._require_machine(data.machine_id)

        topic = ForumTopicModel(
            title=data.title,
            body=data.body,
            machine_id=data.machine_id,
            created_by_id=user_id,
        )
        self.db.add(topic)
        await self._commit("Forum konusu oluşturulamadı")
        await self.db.refresh(topic)
        return await self._get_item(topic.id)

    async def add_comment(
        self,
        topic_id: int,
        data: ForumCommentCreateSchema,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        topic = await self._get_topic(topic_id)
        if topic.is_resolved:
            raise HTTPException(
                status_code=409,
                detail="Konu kapatıldığı için yeni yorum eklenemez",
            )

        self.db.add(
            ForumCommentModel(
                topic_id=topic.id,
                body=data.body,
                created_by_id=user_id,
            )
        )
        # ``updated_at`` doubles as "last activity" for the topic.
        topic.updated_at = datetime.now(timezone.utc)
        await self._commit("Yorum kaydedilemedi")
        return await self._get_item(topic.id)

    async def set_resolved(
        self,
        topic_id: int,
        data: ForumResolveSchema,
        user: UserModel,
    ) -> dict[str, Any]:
        """Close the topic ("çözüldü") or reopen it.

        Only the author or a user with write permission may do this: the
        mechanic who opened the topic decides when the problem is solved.
        """

        topic = await self._get_topic(topic_id)
        ensure_can_manage_topic(user, topic.created_by_id)

        if data.is_resolved:
            topic.is_resolved = True
            topic.resolved_at = datetime.now(timezone.utc)
            topic.resolved_by_id = user.id if user else None
            topic.resolution_note = data.resolution_note
        else:
            topic.is_resolved = False
            topic.resolved_at = None
            topic.resolved_by_id = None
            topic.resolution_note = None

        await self._commit("Konu durumu güncellenemedi")
        return await self._get_item(topic.id)

    async def add_photo(
        self,
        topic_id: int,
        *,
        file_name: Optional[str],
        content_type: Optional[str],
        data: bytes,
        user_id: Optional[int],
    ) -> dict[str, Any]:
        topic = await self._get_topic(topic_id)
        if topic.is_resolved:
            raise HTTPException(
                status_code=409,
                detail="Konu kapatıldığı için fotoğraf eklenemez",
            )

        photo_count = (
            await self.db.execute(
                select(func.count())
                .select_from(ForumTopicPhotoModel)
                .where(ForumTopicPhotoModel.topic_id == topic.id)
            )
        ).scalar() or 0
        if photo_count >= MAX_PHOTOS_PER_TOPIC:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Bir konuya en fazla "
                    f"{MAX_PHOTOS_PER_TOPIC} fotoğraf eklenebilir"
                ),
            )

        try:
            info = validate_photo(file_name, content_type, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        self.db.add(
            ForumTopicPhotoModel(
                topic_id=topic.id,
                file_name=info["file_name"],
                content_type=info["content_type"],
                file_size=info["file_size"],
                file_data=data,
                uploaded_by_id=user_id,
            )
        )
        await self._commit("Fotoğraf kaydedilemedi")
        return await self._get_item(topic.id)

    async def delete_photo(
        self, topic_id: int, photo_id: int, user: UserModel
    ) -> dict[str, Any]:
        topic = await self._get_topic(topic_id)
        ensure_can_manage_topic(user, topic.created_by_id)

        photo = await self.get_photo(topic_id, photo_id)
        await self.db.delete(photo)
        await self._commit("Fotoğraf silinemedi")
        return await self._get_item(topic.id)

    async def delete_topic(
        self, topic_id: int, user: UserModel
    ) -> dict[str, Any]:
        topic = await self._get_topic(topic_id)
        ensure_can_manage_topic(user, topic.created_by_id)

        await self.db.delete(topic)
        await self._commit("Konu silinemedi")
        return {"detail": "Konu silindi"}






