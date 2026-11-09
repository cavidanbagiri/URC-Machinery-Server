# repositories/user_directory_repository.py
"""Read-only user directory behind the dashboard avatar stack.

Only public profile data is exposed (name, position, role label and a
browser-usable photo URL). Passwords and token tables are never touched.
"""

from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.user_model import StatusModel, UserModel
from repositories.auth_repository import user_image_url
from schemas.user_schemas import DEFAULT_TEAM_LIMIT, MAX_TEAM_LIMIT


def clamp_team_limit(limit: Optional[int]) -> int:
    """Keep the avatar request inside ``1..MAX_TEAM_LIMIT``."""

    if limit is None:
        return DEFAULT_TEAM_LIMIT

    return max(1, min(int(limit), MAX_TEAM_LIMIT))


def build_team_member(
    user,
    status_text: Optional[str] = None,
    image_url: str = "",
    current_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Serialize one person for the avatar stack.

    ``user.image`` must already be eager loaded (async sessions cannot lazy
    load); pass the resolved ``image_url`` so this stays a pure function.
    """

    firstname = (user.firstname or "").strip()
    lastname = (user.lastname or "").strip()

    return {
        "id": user.id,
        "firstname": firstname,
        "lastname": lastname,
        "full_name": f"{firstname} {lastname}".strip(),
        "position": user.position or "",
        "status_text": status_text or "",
        "image_url": image_url or "",
        "has_photo": bool(image_url),
        "is_self": current_user_id is not None and user.id == current_user_id,
    }


class UserDirectoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_team(
        self,
        limit: Optional[int] = DEFAULT_TEAM_LIMIT,
        current_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """People for the avatar stack, plus the total user count.

        Order: the signed-in user first, then everybody with a photo, then the
        rest alphabetically — so the overlapping circles are photos as long as
        the team has any.
        """

        rows = await self.db.execute(
            select(UserModel, StatusModel.status)
            .outerjoin(StatusModel, StatusModel.id == UserModel.status_id)
            .options(selectinload(UserModel.image))
            .order_by(
                (UserModel.id == current_user_id).desc(),
                UserModel.image_id.is_(None),
                func.lower(UserModel.firstname),
                func.lower(UserModel.lastname),
                UserModel.id,
            )
            .limit(clamp_team_limit(limit))
        )

        items = [
            build_team_member(
                user,
                status_text=status_text,
                image_url=user_image_url(user),
                current_user_id=current_user_id,
            )
            for user, status_text in rows.all()
        ]

        total = await self.db.scalar(select(func.count(UserModel.id))) or 0
        with_photo = (
            await self.db.scalar(
                select(func.count(UserModel.id)).where(
                    UserModel.image_id.is_not(None)
                )
            )
            or 0
        )

        return {"total": int(total), "with_photo": int(with_photo), "items": items}
