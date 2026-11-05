# routers/forum_router.py
"""API for the forum: topics, comments and topic photos.

Every endpoint requires a valid access token. Opening a topic and uploading a
photo additionally require write permission; commenting is open to every
authenticated user (a discussion, not operational data). Closing or deleting a
topic is limited to its author or a user with write permission (checked in the
repository).
"""

from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from dependencies.permissions import require_write_permission
from models.forum_model import MAX_PHOTO_BYTES
from models.user_model import UserModel
from repositories.forum_repository import ForumRepository, inline_disposition
from schemas.forum_schemas import (
    ForumCommentCreateSchema,
    ForumMachineOptionSchema,
    ForumResolveSchema,
    ForumTopicCreateSchema,
    ForumTopicSchema,
    PaginatedForumTopicsSchema,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# =========================================================
# READ
# =========================================================

@router.get("/topics", response_model=PaginatedForumTopicsSchema)
async def fetch_topics(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, max_length=20),
    mine: bool = Query(False),
    machine_id: Optional[int] = Query(None),
):
    try:
        return await ForumRepository(db).fetch_paginated(
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            mine=mine,
            user_id=current_user.id,
            machine_id=machine_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Forum konuları getirilemedi: {e}"
        )


@router.get("/machines", response_model=list[ForumMachineOptionSchema])
async def fetch_forum_machines(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        return await ForumRepository(db).search_machine_options(
            search=search, limit=limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Makine listesi getirilemedi: {e}"
        )


@router.get("/topics/{topic_id}", response_model=ForumTopicSchema)
async def fetch_topic(
    topic_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await ForumRepository(db).fetch_topic(topic_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Konu açılamadı: {e}")


# =========================================================
# WRITE
# =========================================================

@router.post("/topics", response_model=ForumTopicSchema, status_code=201)
async def create_topic(
    data: ForumTopicCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
):
    try:
        return await ForumRepository(db).create_topic(data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Konu açılamadı: {e}")


@router.post(
    "/topics/{topic_id}/comments",
    response_model=ForumTopicSchema,
    status_code=201,
)
async def create_comment(
    topic_id: int,
    data: ForumCommentCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    try:
        return await ForumRepository(db).add_comment(
            topic_id, data, current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yorum eklenemedi: {e}")


@router.post("/topics/{topic_id}/resolve", response_model=ForumTopicSchema)
async def resolve_topic(
    topic_id: int,
    data: ForumResolveSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    """Mark the topic as resolved (closed) or reopen it."""

    try:
        return await ForumRepository(db).set_resolved(topic_id, data, current_user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Konu durumu güncellenemedi: {e}"
        )


@router.delete("/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    try:
        return await ForumRepository(db).delete_topic(topic_id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Konu silinemedi: {e}")


# =========================================================
# PHOTOS
# =========================================================

@router.post(
    "/topics/{topic_id}/photos",
    response_model=ForumTopicSchema,
    status_code=201,
)
async def upload_topic_photo(
    topic_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(require_write_permission)],
    file: Annotated[UploadFile, File(description="JPEG, PNG veya WEBP")],
):
    try:
        try:
            # Read one byte past the limit so oversized files are detected
            # without buffering an unbounded upload in memory.
            data = await file.read(MAX_PHOTO_BYTES + 1)
        finally:
            await file.close()

        return await ForumRepository(db).add_photo(
            topic_id,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
            user_id=current_user.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fotoğraf yüklenemedi: {e}")


@router.get("/topics/{topic_id}/photos/{photo_id}")
async def fetch_topic_photo(
    topic_id: int,
    photo_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stream a photo. The bytes live in PostgreSQL, hence the backend hop."""

    try:
        photo = await ForumRepository(db).get_photo(topic_id, photo_id)
        return Response(
            content=photo.file_data,
            media_type=photo.content_type or "image/jpeg",
            headers={
                "Content-Disposition": inline_disposition(photo.file_name),
                "Cache-Control": "private, max-age=300",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fotoğraf açılamadı: {e}")


@router.delete(
    "/topics/{topic_id}/photos/{photo_id}",
    response_model=ForumTopicSchema,
)
async def delete_topic_photo(
    topic_id: int,
    photo_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    try:
        return await ForumRepository(db).delete_photo(
            topic_id, photo_id, current_user
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fotoğraf silinemedi: {e}")

