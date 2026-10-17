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
                raise HTTPException(status_code=500, detail="Server configuration error")
            return jwt.encode(encode, secret_key, algorithm)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to create access token")

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
                raise HTTPException(status_code=500, detail="Server configuration error")
            return jwt.encode(encode, secret_key, algorithm)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to create refresh token")

    @staticmethod
    def verify_access_token(req: Request) -> dict:
        authorization = req.headers.get('Authorization')
        if not authorization:
            raise HTTPException(status_code=401, detail='Authorization Error')

        scheme, separator, access_token = authorization.partition(' ')
        access_token = access_token.strip()

        if not separator or scheme.lower() != 'bearer' or not access_token:
            raise HTTPException(status_code=401, detail='Authorization Error')

        secret_key = os.getenv('JWT_SECRET_KEY')
        algorithm = os.getenv('JWT_ALGORITHM')
        if not secret_key or not algorithm:
            raise HTTPException(status_code=500, detail='Server configuration error')

        try:
            payload = jwt.decode(access_token, secret_key, algorithms=[algorithm])
            return payload
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail='Access token expired')
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail='Authorization Error')

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
                raise HTTPException(status_code=401, detail="Refresh token is required")

            secret_key = os.getenv('JWT_REFRESH_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')

            if not secret_key or not algorithm:
                raise HTTPException(status_code=500, detail="Server configuration error")

            # Decode and verify the token
            payload = jwt.decode(refresh_token, secret_key, algorithms=[algorithm])

            # Validate required fields
            if 'sub' not in payload:
                raise HTTPException(status_code=401, detail="Invalid token: missing subject")

            return payload

        except HTTPException:
            raise
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        except Exception:
            raise HTTPException(status_code=500, detail="Token verification failed")