import asyncio
from typing import Union, Dict, Any

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import NoResultFound, DBAPIError

from sqlalchemy.orm import selectinload

from sqlalchemy.ext.asyncio import AsyncSession

from auth.refresh_token_handler import DeleteRefreshTokenRepository
from auth.token_handler import TokenHandler
from core.permissions import DEFAULT_REGISTRATION_STATUS_ID
from models.user_model import UserModel, TokenModel, StatusModel
from schemas.auth_schemas import UserLoginSchema
from utils.hash_password import PasswordHash


class RefreshTokenRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_refresh_token(self, user_id: int) -> Union[TokenModel, None]:
        result = await self.db.execute(
            select(TokenModel)
            .where(TokenModel.user_id == user_id)
            .order_by(TokenModel.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def delete_refresh_token(self, user_id: int) -> None:
        try:
            await self.db.execute(delete(TokenModel).where(TokenModel.user_id == user_id))
        except Exception as ex:
            raise HTTPException(status_code=404, detail='Kullanıcı bulunamadı')

    async def save_refresh_token(self, user_id: int, refresh_token: str, access_token: str):
        """Save both access and refresh tokens for user"""
        from datetime import datetime, timezone, timedelta

        try:
            # Add await here - this was likely missing
            result = await self.db.execute(
                select(TokenModel)
                .where(TokenModel.user_id == user_id)
                .order_by(TokenModel.id.desc())
                .limit(1)
            )
            token_record = result.scalars().first()

            expires_at = datetime.now(timezone.utc) + timedelta(days=30)

            if token_record:
                # Update existing tokens
                token_record.access_token = access_token
                token_record.refresh_token = refresh_token
                token_record.expires_at = expires_at
            else:
                # Create new token record
                token_record = TokenModel(
                    user_id=user_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at=expires_at
                )
                self.db.add(token_record)

            await self.db.commit()
            return True
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="Belirteç kaydedilemedi")


class UserRegisterRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.refresh_token_repo = RefreshTokenRepository(self.db)
        self.h_password = PasswordHash()

    async def register(self, register_data):
        # Check email
        data = await self.db.execute(
            select(UserModel).where(UserModel.email == register_data.email.lower())
        )
        if data.scalars().first():
            raise HTTPException(status_code=409, detail="Bu e-posta adresi zaten kayıtlı")

        # Public registration must never be able to choose a privileged role.
        status_result = await self.db.execute(
            select(StatusModel.id).where(
                StatusModel.id == DEFAULT_REGISTRATION_STATUS_ID
            )
        )
        if status_result.scalar_one_or_none() is None:
            # Migration/seed data is missing; fail explicitly instead of a 500 FK error.
            raise HTTPException(
                status_code=503,
                detail="Kayıt şu anda kullanılamıyor",
            )

        # Argon2 hashing is CPU-bound; keep it off the event loop.
        hashed_password = await asyncio.to_thread(
            self.h_password.hash_password, register_data.password
        )

        user = UserModel(
            firstname=register_data.firstname.strip().lower(),
            lastname=register_data.lastname.strip().lower(),
            email=register_data.email.lower(),
            password=hashed_password,
            status_id=DEFAULT_REGISTRATION_STATUS_ID,
        )

        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
        except Exception:
            await self.db.rollback()
            raise

        # Generate tokens
        token_data = {'sub': str(user.id), 'username': user.firstname + ' ' + user.lastname}
        access_token = TokenHandler.generate_access_token(token_data)
        refresh_token = TokenHandler.generate_refresh_token(token_data)

        await self.refresh_token_repo.save_refresh_token(user.id, refresh_token, access_token)

        # After finding the user, fetch status text
        status_result = await self.db.execute(
            select(StatusModel.status).where(StatusModel.id == user.status_id)
        )
        status_text = status_result.scalar()

        return {
            'user': {
                'id': user.id,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'username': user.firstname + ' ' + user.lastname,
                'email': user.email,
                'status_id': user.status_id,  # Changed from 'status' to 'status_id'
                'status_text': status_text,
            },
            'access_token': access_token,
            'refresh_token': refresh_token
        }


class CheckUserAvailable:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.h_password = PasswordHash()

    async def check_user_exists(self, login_data: UserLoginSchema) -> UserModel:
        # Eagerly load status relationship
        query = select(UserModel).where(
            UserModel.email == login_data.email.lower()
        ).options(selectinload(UserModel.status))

        data = await self.db.execute(query)
        user = data.scalar()

        if user:
            pass_verify = await self.h_password.verify(user.password, login_data.password)
            if pass_verify:
                return user

        # Same response for unknown email and wrong password: no account enumeration.
        raise HTTPException(status_code=401, detail="E-posta adresi veya şifre hatalı")

class UserLoginRepository:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.check_user_available = CheckUserAvailable(self.db)
        self.refresh_token_repo = RefreshTokenRepository(self.db)

    # In UserLoginRepository
    async def login(self, login_data: UserLoginSchema) -> dict:
        try:
            user = await self.check_user_available.check_user_exists(login_data)

            token_data = {'sub': str(user.id), 'username': user.firstname + ' ' + user.lastname}
            access_token = TokenHandler.generate_access_token(token_data)
            refresh_token = TokenHandler.generate_refresh_token(token_data)

            await self.refresh_token_repo.save_refresh_token(user.id, refresh_token, access_token)

            # After finding the user, fetch status text
            status_result = await self.db.execute(
                select(StatusModel.status).where(StatusModel.id == user.status_id)
            )
            status_text = status_result.scalar()

            return {
                'user': {
                    'id': user.id,
                    'firstname': user.firstname,
                    'lastname': user.lastname,
                    'username': user.firstname + ' ' + user.lastname,
                    'email': user.email,
                    'status_id': user.status_id,  # Changed from 'status' to 'status_id'
                    'status_text': status_text
                },
                'access_token': access_token,
                'refresh_token': refresh_token
            }
        except HTTPException as ex:
            raise ex
        except Exception as ex:
            # print("ex -> {}".format(ex))
            print(ex)
            raise HTTPException(status_code=500, detail="Giriş başarısız oldu")

    @staticmethod
    async def get_user_with_profile(db: AsyncSession, user_id: int) -> Dict[str, Any]:
        """Get complete user data with profile for refresh token response"""

        try:
            # Query user with profile relationship
            query = select(UserModel).where(UserModel.id == user_id)
            result = await db.execute(query)
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

            # After finding the user, fetch status text
            status_result = await db.execute(
                select(StatusModel.status).where(StatusModel.id == user.status_id)
            )
            status_text = status_result.scalar()

            # Return user data in the same format as login method
            return {
                'id': user.id,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'username': user.firstname + ' ' + user.lastname,
                'email': user.email,
                'status_id': user.status_id,  # Changed from 'status' to 'status_id'
                'status_text': status_text
            }


        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Kullanıcı bilgileri alınamadı")


class UserLogoutRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def logout(self, user_id: int):
        """
        Logs out a user by deleting their refresh token.

        :param user_id: ID of the user.
        :return: True if logout is successful, False otherwise.
        """
        try:
            await DeleteRefreshTokenRepository(self.db).delete_refresh_token(user_id)
            return {"detail": "Çıkış yapıldı"}
        except NoResultFound:
            return {"detail": "Oturum zaten kapalı"}
        except DBAPIError as e:
            raise HTTPException(status_code=500, detail="Çıkış yapılırken sunucu hatası oluştu")
        except Exception as e:
            raise HTTPException(status_code=500, detail="Beklenmeyen bir hata oluştu")
