# dependencies/permissions.py
from typing import Annotated

from fastapi import Depends, HTTPException, status

from core.permissions import WRITE_PERMISSION_VALUES, get_permission_value
from dependencies.auth import get_current_user
from models.user_model import UserModel


async def require_write_permission(
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> UserModel:
    """
    Create / Update / Delete üçün.
    Status 1, 2, 3 (dəyər 1, 10, 100) icazəlidir.
    Status 4 (dəyər 1000) yalnız oxuya bilər → 403.
    """
    value = get_permission_value(current_user.status_id)

    if value not in WRITE_PERMISSION_VALUES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu əməliyyat üçün icazəniz yoxdur",
        )

    return current_user