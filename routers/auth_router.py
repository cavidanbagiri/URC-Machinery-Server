
from typing import Annotated

from fastapi import APIRouter, Depends, Response, HTTPException, Request

from sqlalchemy.ext.asyncio import AsyncSession

from auth.refresh_token_handler import VerifyRefreshTokenMiddleware
from auth.token_handler import TokenHandler
from database.setup import get_db

from repositories.auth_repository import UserRegisterRepository, UserLoginRepository, UserLogoutRepository

from schemas import auth_schemas
from schemas.auth_schemas import UserLoginSchema

router = APIRouter()


@router.post('/register', status_code=201)
async def register(response: Response, register_data: auth_schemas.UserRegisterSchema,
                   db_session: Annotated[AsyncSession, Depends(get_db)]):
    repository = UserRegisterRepository(db_session)

    try:
        print(register_data)
        data = await repository.register(register_data)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        response.set_cookie('refresh_token', data.get('refresh_token'),
                            httponly=True,
                            secure=True,
                            samesite="none"
                            )

        return {
            'user': data.get('user'),
            'access_token': data.get('access_token')
        }

    except HTTPException as ex:
        raise ex
    except Exception as ex:
        print('ex is ', ex)
        raise HTTPException(500, f'Internal server error {ex}')





@router.post('/login', status_code=201)
async def login(response: Response, login_data: UserLoginSchema, db_session: Annotated[AsyncSession,  Depends(get_db)]):

    repository = UserLoginRepository(db_session)

    try:
        print(login_data)
        data = await repository.login(login_data)


        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        response.set_cookie('refresh_token', data.get('refresh_token'),
                            httponly=True,
                            secure=True,
                            samesite="none"
                            )
        print({
            'user': data.get('user'),
            'access_token': data.get('access_token')
        })
        return {
            'user': data.get('user'),
            'access_token': data.get('access_token')
        }

    except HTTPException as ex:
        raise ex
    except Exception as ex:  # Catch all other exceptions
        raise HTTPException(500, 'Internal server error')



@router.post("/refresh", status_code=200)
async def refresh_token(response: Response, request: Request, db: AsyncSession = Depends(get_db)):

    middleware = VerifyRefreshTokenMiddleware(db)
    try:
        user_info = await middleware.validate_refresh_token(request, response)
        if not user_info:
            response.delete_cookie(key="refresh_token")
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        completed_user = await UserLoginRepository.get_user_with_profile(db, int(user_info.get('user').get('sub')))

        return {
            "access_token": user_info.get("access_token"),
            "user": completed_user,
        }

    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while refreshing the token {e}")




@router.post('/logout', status_code=200)
async def logout(
        request: Request,
        response: Response,
        db: AsyncSession = Depends(get_db)
):
    # Get refresh token from cookies
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        # If no refresh token exists, just return success (already logged out)
        response.delete_cookie(
            key="refresh_token",
            secure=True,
            samesite="none",
            httponly=True,
            path="/"
        )
        return {"message": "Logout successful"}

    user_logout_repository = UserLogoutRepository(db)
    try:
        # Try to verify the refresh token to get user ID
        user_payload = TokenHandler.verify_refresh_token(refresh_token)
        user_id = int(user_payload.get('sub'))

        # Perform server-side logout
        result = await user_logout_repository.logout(user_id)

        # Always clear the cookie regardless of server-side result
        response.delete_cookie(
            key="refresh_token",
            secure=True,
            samesite="none",
            httponly=True,
            path="/"
        )

        return {"message": "Logout successful"}

    except HTTPException as ex:
        # Even if token verification fails, clear the cookie
        response.delete_cookie(
            key="refresh_token",
            secure=True,
            samesite="none",
            httponly=True,
            path="/"
        )
        return {"message": "Logout successful"}

    except Exception as e:
        # Clear cookie on any error
        response.delete_cookie(
            key="refresh_token",
            secure=True,
            samesite="none",
            httponly=True,
            path="/"
        )
        return {"message": "Logout successful"}

