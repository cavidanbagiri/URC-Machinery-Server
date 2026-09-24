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
            encode.update({"exp": datetime.now(timezone.utc) + timedelta(days=2)})
            secret_key = os.getenv('JWT_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')
            access_token = jwt.encode(encode, secret_key, algorithm)
            return access_token
        except Exception as ex:
            raise HTTPException(status_code=500, detail=f"Failed to create access token {ex}")

    @staticmethod
    def generate_refresh_token(user_data: dict) -> str:  # SYNC method
        try:
            encode = user_data.copy()
            encode.update({"exp": datetime.now(timezone.utc) + timedelta(days=30)})
            secret_key = os.getenv('JWT_REFRESH_SECRET_KEY')
            algorithm = os.getenv('JWT_ALGORITHM')
            refresh_token = jwt.encode(encode, secret_key, algorithm)
            return refresh_token
        except Exception as ex:
            raise HTTPException(status_code=500, detail=f"Failed to create refresh token {ex}")

    @staticmethod
    def verify_access_token(req: Request) -> dict:
        if req.headers.get('Authorization'):
            access_token = req.headers.get('Authorization').split(' ')[1]
            if access_token:
                try:
                    secret_key = os.getenv('JWT_SECRET_KEY')
                    algorithm = os.getenv('JWT_ALGORITHM')
                    payload = jwt.decode(access_token, secret_key, algorithm)
                    return payload
                except InvalidTokenError as ex:
                    raise HTTPException(status_code=401, detail=f'Authorization Error {ex}')
            else:
                raise HTTPException(status_code=401, detail='Authorization Error')
        else:
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

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token expired")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        except Exception as e:
            raise HTTPException(status_code=500, detail="Token verification failed")