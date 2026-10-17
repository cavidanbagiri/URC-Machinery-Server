"""Offline regression tests for auth hardening.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not connect to PostgreSQL.
"""

import os
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from auth.refresh_token_handler import VerifyRefreshTokenMiddleware
from auth.token_handler import TokenHandler
from core.permissions import get_permission_value
from schemas.auth_schemas import UserRegisterSchema

os.environ.setdefault("JWT_SECRET_KEY", "test-access-secret-" + "a" * 40)
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-refresh-secret-" + "b" * 40)
os.environ.setdefault("JWT_ALGORITHM", "HS256")


def make_request(authorization: bytes | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


class RegistrationSchemaTests(unittest.TestCase):
    def test_status_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            UserRegisterSchema(
                firstname="A",
                lastname="B",
                email="a@example.com",
                password="12345678",
                status_id=1,
            )

    def test_valid_payload_has_no_status(self):
        data = UserRegisterSchema(
            firstname="  A  ",
            lastname="  B  ",
            email="a@example.com",
            password="12345678",
        )
        self.assertEqual(data.firstname, "A")
        self.assertNotIn("status_id", data.model_dump())


class AccessTokenTests(unittest.TestCase):
    def test_malformed_headers_are_401(self):
        for header in (b"Bearer", b"Basic abc", b"Bearer   "):
            with self.subTest(header=header):
                with self.assertRaises(HTTPException) as ctx:
                    TokenHandler.verify_access_token(make_request(header))
                self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_header_is_401(self):
        with self.assertRaises(HTTPException) as ctx:
            TokenHandler.verify_access_token(make_request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_round_trip(self):
        token = TokenHandler.generate_access_token(
            {"sub": "7", "username": "Test User"}
        )
        payload = TokenHandler.verify_access_token(
            make_request(f"Bearer {token}".encode())
        )
        self.assertEqual(payload["sub"], "7")

    def test_permission_mapping(self):
        self.assertEqual(get_permission_value(1), 1)
        self.assertEqual(get_permission_value(4), 1000)
        self.assertEqual(get_permission_value(999), 0)


class _EmptyScalars:
    def first(self):
        return None


class _EmptyResult:
    def scalars(self):
        return _EmptyScalars()


class _FakeDB:
    async def execute(self, *args, **kwargs):
        return _EmptyResult()


class RefreshTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_refresh_token_is_401(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/refresh",
                "headers": [(b"cookie", b"refresh_token=unknown")],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await VerifyRefreshTokenMiddleware(_FakeDB()).validate_refresh_token(
                request, Response()
            )
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
