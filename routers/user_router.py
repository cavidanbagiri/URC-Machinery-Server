# routers/user_router.py
"""Read-only user directory (dashboard avatar stack)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_db
from dependencies.auth import get_current_user
from models.user_model import UserModel
from repositories.user_directory_repository import UserDirectoryRepository
from schemas.user_schemas import (
    DEFAULT_TEAM_LIMIT,
    MAX_TEAM_LIMIT,
    TeamDirectorySchema,
)

# A valid access token is enough: the directory holds nothing but names,
# job titles and profile photos that every signed-in user already sees.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/team", response_model=TeamDirectorySchema)
async def fetch_team(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    limit: int = Query(DEFAULT_TEAM_LIMIT, ge=1, le=MAX_TEAM_LIMIT),
):
    """Team members for the avatar stack plus the total user count."""

    try:
        return await UserDirectoryRepository(db).list_team(
            limit=limit, current_user_id=current_user.id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Kullanıcı listesi getirilemedi: {e}"
        )
