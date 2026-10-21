"""Offline tests for the machine photo storage helpers and response schemas.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

No database or S3 connection is used: boto3 only signs the URL locally.
"""

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from schemas.machines_schemas import (
    FetchAllMachineSchema,
    FetchMachinePhotoSchema,
)
from services.storage_service import (
    ALLOWED_IMAGE_TYPES,
    build_object_key,
    build_photo_url,
    max_upload_bytes,
    max_upload_mb,
    resolve_content_type,
    validate_size,
)


PUBLIC_ENV = {
    "S3_ENDPOINT": "https://s3.cloud.ru",
    "S3_REGION": "ru-central-1",
    "S3_BUCKET": "urc-machinery-images",
    "S3_ACCESS_KEY_ID": "tenant:key",
    "S3_SECRET_ACCESS_KEY": "secret",
    "S3_PUBLIC_BASE_URL": "https://s3.cloud.ru/urc-machinery-images",
}


class ResolveContentTypeTests(unittest.TestCase):
    def test_accepts_supported_types(self):
        for content_type in ALLOWED_IMAGE_TYPES:
            self.assertEqual(
                resolve_content_type("photo.bin", content_type), content_type
            )

    def test_normalizes_image_jpg(self):
        self.assertEqual(
            resolve_content_type("photo.jpg", "image/jpg"), "image/jpeg"
        )

    def test_strips_parameters(self):
        self.assertEqual(
            resolve_content_type("a.png", "image/png; charset=binary"),
            "image/png",
        )

    def test_falls_back_to_extension_for_octet_stream(self):
        self.assertEqual(
            resolve_content_type("photo.WEBP", "application/octet-stream"),
            "image/webp",
        )
        self.assertEqual(resolve_content_type("photo.jpeg", None), "image/jpeg")

    def test_rejects_non_image(self):
        for filename, content_type in (
            ("doc.pdf", "application/pdf"),
            ("anim.gif", "image/gif"),
            ("unknown", "application/octet-stream"),
            ("unknown", None),
        ):
            with self.assertRaises(ValueError):
                resolve_content_type(filename, content_type)


class UploadLimitTests(unittest.TestCase):
    def test_default_limit_is_ten_megabytes(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(max_upload_mb(), 10)
            self.assertEqual(max_upload_bytes(), 10 * 1024 * 1024)

    def test_invalid_limit_falls_back(self):
        with patch.dict(os.environ, {"S3_MAX_UPLOAD_MB": "abc"}):
            self.assertEqual(max_upload_mb(), 10)
        with patch.dict(os.environ, {"S3_MAX_UPLOAD_MB": "0"}):
            self.assertEqual(max_upload_mb(), 10)

    def test_validate_size(self):
        with patch.dict(os.environ, {"S3_MAX_UPLOAD_MB": "1"}):
            validate_size(1)
            validate_size(1024 * 1024)
            with self.assertRaises(ValueError):
                validate_size(0)
            with self.assertRaises(ValueError):
                validate_size(1024 * 1024 + 1)


class ObjectKeyTests(unittest.TestCase):
    def test_key_layout(self):
        key = build_object_key(42, "image/png")
        self.assertTrue(key.startswith("machines/42/"))
        self.assertTrue(key.endswith(".png"))
        self.assertEqual(len(key.split("/")), 3)

    def test_keys_are_unique(self):
        self.assertNotEqual(
            build_object_key(1, "image/jpeg"),
            build_object_key(1, "image/jpeg"),
        )

    def test_extension_matches_type(self):
        for content_type, extension in ALLOWED_IMAGE_TYPES.items():
            self.assertTrue(build_object_key(7, content_type).endswith(extension))


class PhotoUrlTests(unittest.TestCase):
    def test_public_base_url(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            self.assertEqual(
                build_photo_url("machines/5/abc.png"),
                "https://s3.cloud.ru/urc-machinery-images/machines/5/abc.png",
            )

    def test_trailing_slash_is_trimmed(self):
        env = dict(PUBLIC_ENV, S3_PUBLIC_BASE_URL="https://cdn.example.com/bucket/")
        with patch.dict(os.environ, env):
            self.assertEqual(
                build_photo_url("machines/5/abc.png"),
                "https://cdn.example.com/bucket/machines/5/abc.png",
            )

    def test_special_characters_are_quoted(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            self.assertIn("a%20b.png", build_photo_url("machines/5/a b.png"))

    def test_empty_key(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            self.assertEqual(build_photo_url(""), "")

    def test_presigned_fallback_without_public_base(self):
        env = dict(PUBLIC_ENV, S3_PUBLIC_BASE_URL="")
        with patch.dict(os.environ, env):
            url = build_photo_url("machines/5/abc.png")
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("urc-machinery-images", url)

    def test_returns_empty_when_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(build_photo_url("machines/5/abc.png"), "")


def make_photo(**overrides):
    values = {
        "id": 3,
        "machine_id": 5,
        "object_key": "machines/5/abc.png",
        "original_filename": "abc.png",
        "content_type": "image/png",
        "size_bytes": 1234,
        "is_primary": True,
        "uploaded_by_id": 1,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_machine(**overrides):
    values = {
        "id": 5,
        "identification_no": "URC-1",
        "vin_no": None,
        "plate_no": None,
        "technical_character": None,
        "production_year": None,
        "weight": None,
        "dimension": None,
        "engine_power": None,
        "engine_mark_model": None,
        "engine_identity": None,
        "territory_id": None,
        "type_id": None,
        "subtype_id": None,
        "car_mark_id": None,
        "car_model_id": None,
        "company_id": None,
        "created_by_id": None,
        "created_at": None,
        "status_id": 1,
        "photos": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PhotoSchemaTests(unittest.TestCase):
    def test_url_is_filled_from_public_base(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            schema = FetchMachinePhotoSchema.model_validate(make_photo())

        self.assertEqual(
            schema.url,
            "https://s3.cloud.ru/urc-machinery-images/machines/5/abc.png",
        )
        self.assertTrue(schema.is_primary)

    def test_url_defaults_to_empty_without_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            schema = FetchMachinePhotoSchema.model_validate(make_photo())

        self.assertEqual(schema.url, "")

    def test_explicit_url_is_not_overwritten(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            schema = FetchMachinePhotoSchema.model_validate(
                make_photo(url="https://example.com/custom.png")
            )

        self.assertEqual(schema.url, "https://example.com/custom.png")

    def test_machine_schema_defaults_to_no_photos(self):
        schema = FetchAllMachineSchema.model_validate(make_machine())
        self.assertEqual(schema.photos, [])

    def test_machine_schema_serializes_photos(self):
        with patch.dict(os.environ, PUBLIC_ENV):
            schema = FetchAllMachineSchema.model_validate(
                make_machine(photos=[make_photo()])
            )

        payload = schema.model_dump()
        self.assertEqual(len(payload["photos"]), 1)
        self.assertEqual(
            payload["photos"][0]["url"],
            "https://s3.cloud.ru/urc-machinery-images/machines/5/abc.png",
        )


if __name__ == "__main__":
    unittest.main()

