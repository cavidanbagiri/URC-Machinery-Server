import os
from datetime import datetime, timezone, timedelta

import jwt

from fastapi import Request, HTTPException

from sqlalchemy import update, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from auth.token_handler import TokenHandler
from core.cookies import refresh_cookie_options

from models.user_model import TokenModel



class VerifyRefreshTokenMiddleware:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_refresh_token(self, request: Request, response: Response):

        refresh_token = request.cookies.get('refresh_token')

        if not refresh_token:
            raise HTTPException(status_code=401, detail="Please login before executing")

        try:
            # The token must exist in the DB (revoked/rotated tokens are rejected).
            user_id = await SearchRefreshTokenRepository(self.db).search_refresh_token(refresh_token)

            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")

            secret_key = os.getenv('JWT_REFRESH_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')
            if not secret_key or not algorithm:
                raise HTTPException(status_code=500, detail="Server configuration error")

            payload = jwt.decode(
                refresh_token,
                secret_key,
                algorithms=[algorithm],
            )

            subject = payload.get('sub')
            try:
                token_user_id = int(subject)
            except (TypeError, ValueError):
                raise HTTPException(status_code=401, detail="Invalid refresh token")

            if token_user_id != int(user_id):
                raise HTTPException(status_code=401, detail="Invalid refresh token")

            if "exp" not in payload:
                raise HTTPException(status_code=401, detail="Invalid refresh token")

            # Access token always updated
            access_token = TokenHandler.generate_access_token(payload)

            # Refresh token will check expiry date, less than 7 days, will change
            exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            now = datetime.now(timezone.utc)
            if exp - now < timedelta(days=7):
                new_refresh_token = TokenHandler.generate_refresh_token(payload)
                await UpdateRefreshTokenRepository(self.db).update_refresh_token(
                    token_user_id, new_refresh_token
                )
                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    **refresh_cookie_options(),
                )
            else:
                new_refresh_token = refresh_token

            return {
                'access_token': access_token,
                'refresh_token': new_refresh_token,
                'user': payload
            }

        except HTTPException:
            raise
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Expired refresh token")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="An error occurred while validating the refresh token",
            )


class UpdateRefreshTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_refresh_token(self, user_id: int, refresh_token: str):
        """
        Updates a refresh token for a user.

        :param user_id: ID of the user.
        :param refresh_token: Refresh token to update.
        """
        try:
            await self.db.execute(
                update(TokenModel)
                .where(TokenModel.user_id == user_id)
                .values(refresh_token=refresh_token)
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise HTTPException(
                status_code=500, detail="Error updating refresh token"
            )




class DeleteRefreshTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete_refresh_token(self, user_id: int) -> None:

        try:

            result = await self.db.execute(
                select(TokenModel).where(TokenModel.user_id == user_id)
            )

            token = result.scalars().first()

            if not token:
                return

            # Delete Token
            await self.db.execute(
                delete(TokenModel).where(TokenModel.user_id == user_id)
            )
            await self.db.commit()

        except Exception as e:
            raise


class SearchRefreshTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_refresh_token(self, refresh_token: str):

        result = await self.db.execute(
            select(TokenModel).where(TokenModel.refresh_token == refresh_token)
        )
        token = result.scalars().first()
        return token.user_id if token else None