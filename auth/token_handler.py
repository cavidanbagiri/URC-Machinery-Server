import os
from datetime import datetime, timezone, timedelta

from fastapi.requests import Request

import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from fastapi import HTTPException

class TokenHandler:

    @staticmethod
    def generate_access_token(user_data: dict) -> str:  # SYNC method
        try:
            encode = user_data.copy()
            encode.update({
                "iat": datetime.now(timezone.utc),
                "exp": datetime.now(timezone.utc) + timedelta(days=2),
            })
            secret_key = os.getenv('JWT_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')
            if not secret_key or not algorithm:
                raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası")
            return jwt.encode(encode, secret_key, algorithm)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Erişim belirteci oluşturulamadı")

    @staticmethod
    def generate_refresh_token(user_data: dict) -> str:  # SYNC method
        try:
            encode = user_data.copy()
            encode.update({
                "iat": datetime.now(timezone.utc),
                "exp": datetime.now(timezone.utc) + timedelta(days=30),
            })
            secret_key = os.getenv('JWT_REFRESH_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')
            if not secret_key or not algorithm:
                raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası")
            return jwt.encode(encode, secret_key, algorithm)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Yenileme belirteci oluşturulamadı")

    @staticmethod
    def verify_access_token(req: Request) -> dict:
        authorization = req.headers.get('Authorization')
        if not authorization:
            raise HTTPException(status_code=401, detail='Yetkilendirme hatası')

        scheme, separator, access_token = authorization.partition(' ')
        access_token = access_token.strip()

        if not separator or scheme.lower() != 'bearer' or not access_token:
            raise HTTPException(status_code=401, detail='Yetkilendirme hatası')

        secret_key = os.getenv('JWT_SECRET_KEY')
        algorithm = os.getenv('JWT_ALGORITHM')
        if not secret_key or not algorithm:
            raise HTTPException(status_code=500, detail='Sunucu yapılandırma hatası')

        try:
            payload = jwt.decode(access_token, secret_key, algorithms=[algorithm])
            return payload
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail='Erişim belirtecinin süresi doldu')
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail='Yetkilendirme hatası')

    @staticmethod
    def verify_refresh_token(refresh_token: str) -> dict:
        """
        Verify and decode a refresh token.

        :param refresh_token: The refresh token to verify
        :return: Decoded token payload if valid
        :raises HTTPException: If token is invalid or expired
        """
        try:
            if not refresh_token:
                raise HTTPException(status_code=401, detail="Yenileme belirteci gerekli")

            secret_key = os.getenv('JWT_REFRESH_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')

            if not secret_key or not algorithm:
                raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası")

            # Decode and verify the token
            payload = jwt.decode(refresh_token, secret_key, algorithms=[algorithm])

            # Validate required fields
            if 'sub' not in payload:
                raise HTTPException(status_code=401, detail="Geçersiz belirteç: kullanıcı bilgisi eksik")

            return payload

        except HTTPException:
            raise
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Yenileme belirtecinin süresi doldu")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Yenileme belirteci geçersiz")
        except Exception:
            raise HTTPException(status_code=500, detail="Belirteç doğrulanamadı")