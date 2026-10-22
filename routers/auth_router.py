
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, HTTPException, Request

from sqlalchemy.ext.asyncio import AsyncSession

from auth.refresh_token_handler import VerifyRefreshTokenMiddleware
from auth.token_handler import TokenHandler
from core.cookies import delete_cookie_options, refresh_cookie_options
from database.setup import get_db
from dependencies.auth import get_current_user
from models.user_model import UserModel

from repositories.auth_repository import UserRegisterRepository, UserLoginRepository, UserLogoutRepository

from schemas import auth_schemas
from schemas.auth_schemas import UserLoginSchema

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post('/register', status_code=201)
async def register(response: Response, register_data: auth_schemas.UserRegisterSchema,
                   db_session: Annotated[AsyncSession, Depends(get_db)]):
    repository = UserRegisterRepository(db_session)

    try:
        data = await repository.register(register_data)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        response.set_cookie(
            'refresh_token',
            data.get('refresh_token'),
            **refresh_cookie_options(),
        )

        return {
            'user': data.get('user'),
            'access_token': data.get('access_token')
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Registration failed")
        raise HTTPException(500, 'Sunucu hatası')





@router.post('/login', status_code=200)
async def login(response: Response, login_data: UserLoginSchema, db_session: Annotated[AsyncSession,  Depends(get_db)]):
    print(login_data)
    repository = UserLoginRepository(db_session)

    try:
        data = await repository.login(login_data)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        response.set_cookie(
            'refresh_token',
            data.get('refresh_token'),
            **refresh_cookie_options(),
        )

        return {
            'user': data.get('user'),
            'access_token': data.get('access_token')
        }

    except HTTPException as hex:
        print("err: {}".format(hex))
        raise
    except Exception as ex:
        print("exc err {}".format(ex))
        logger.exception("Login failed")
        raise HTTPException(500, 'Sunucu hatası')



@router.post("/refresh", status_code=200)
async def refresh_token(response: Response, request: Request, db: AsyncSession = Depends(get_db)):

    middleware = VerifyRefreshTokenMiddleware(db)
    try:
        user_info = await middleware.validate_refresh_token(request, response)
        if not user_info:
            raise HTTPException(status_code=401, detail="Yenileme belirteci geçersiz veya süresi dolmuş")

        payload = user_info.get('user') or {}
        try:
            user_id = int(payload.get('sub'))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Yenileme belirteci geçersiz")

        completed_user = await UserLoginRepository.get_user_with_profile(db, user_id)

        return {
            "access_token": user_info.get("access_token"),
            "user": completed_user,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Token refresh failed")
        raise HTTPException(
            status_code=500,
            detail="Belirteç yenilenirken bir hata oluştu",
        )




@router.get('/me', status_code=200)
async def me(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's public profile."""
    return await UserLoginRepository.get_user_with_profile(db, current_user.id)


@router.post('/logout', status_code=200)
async def logout(
        request: Request,
        response: Response,
        db: AsyncSession = Depends(get_db)
):
    # Get refresh token from cookies
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        response.delete_cookie(key="refresh_token", **delete_cookie_options())
        return {"message": "Çıkış başarılı"}

    user_logout_repository = UserLogoutRepository(db)
    try:
        # Try to verify the refresh token to get user ID
        user_payload = TokenHandler.verify_refresh_token(refresh_token)
        user_id = int(user_payload.get('sub'))

        # Perform server-side logout
        await user_logout_repository.logout(user_id)

        return {"message": "Çıkış başarılı"}

    except (HTTPException, TypeError, ValueError):
        # Even if token verification fails, logout is idempotent.
        return {"message": "Çıkış başarılı"}

    except Exception:
        logger.exception("Logout failed")
        return {"message": "Çıkış başarılı"}

    finally:
        # Always clear the cookie regardless of server-side result.
        response.delete_cookie(key="refresh_token", **delete_cookie_options())

