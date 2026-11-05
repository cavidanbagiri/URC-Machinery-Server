"""Offline regression tests for the forum rules.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover request validation, the photo
guard rails and the "author or manager" rule used when a topic is closed.
"""

import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from models.forum_model import (
    MAX_BODY_LENGTH,
    MAX_COMMENT_LENGTH,
    MAX_PHOTOS_PER_TOPIC,
    MAX_PHOTO_BYTES,
    MAX_TITLE_LENGTH,
    ForumTopicPhotoModel,
)
from models.user_model import UserModel
from repositories.forum_repository import (
    can_manage_topic,
    clamp_pagination,
    ensure_can_manage_topic,
    has_image_signature,
    inline_disposition,
    normalize_status_filter,
    sanitize_file_name,
    validate_photo,
)
from schemas.forum_schemas import (
    ForumCommentCreateSchema,
    ForumResolveSchema,
    ForumTopicCreateSchema,
    normalize_title,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + (36).to_bytes(4, "little") + b"WEBP" + b"\x00" * 24


def user(status_id: int, user_id: int = 7) -> UserModel:
    return UserModel(id=user_id, status_id=status_id)


class ForumTopicCreateSchemaTests(unittest.TestCase):
    def test_accepts_and_trims_values(self):
        parsed = ForumTopicCreateSchema(
            title="  Lastik patladı  ",
            body="  Yedek parça acil alınmalı.  ",
            machine_id=12,
        )
        self.assertEqual(parsed.title, "Lastik patladı")
        self.assertEqual(parsed.body, "Yedek parça acil alınmalı.")
        self.assertEqual(parsed.machine_id, 12)

    def test_machine_is_optional(self):
        parsed = ForumTopicCreateSchema(title="Konu", body="Açıklama")
        self.assertIsNone(parsed.machine_id)

    def test_windows_newlines_are_normalized(self):
        parsed = ForumTopicCreateSchema(
            title="Konu", body="Satır 1\r\nSatır 2"
        )
        self.assertEqual(parsed.body, "Satır 1\nSatır 2")

    def test_blank_title_is_rejected(self):
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(title="   ", body="Açıklama")

    def test_blank_body_is_rejected(self):
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(title="Konu", body="\n\n")

    def test_lengths_are_limited(self):
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(
                title="t" * (MAX_TITLE_LENGTH + 1), body="Açıklama"
            )
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(
                title="Konu", body="b" * (MAX_BODY_LENGTH + 1)
            )

    def test_machine_id_must_be_positive(self):
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(title="Konu", body="Açıklama", machine_id=0)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ForumTopicCreateSchema(
                title="Konu", body="Açıklama", priority="high"
            )

    def test_normalize_title_helper(self):
        self.assertEqual(normalize_title("  Başlık  "), "Başlık")


class ForumCommentSchemaTests(unittest.TestCase):
    def test_comment_is_trimmed_and_keeps_newlines(self):
        parsed = ForumCommentCreateSchema(body="  İlk satır\nİkinci satır  ")
        self.assertEqual(parsed.body, "İlk satır\nİkinci satır")

    def test_blank_comment_is_rejected(self):
        with self.assertRaises(ValidationError):
            ForumCommentCreateSchema(body="   ")

    def test_comment_length_is_limited(self):
        with self.assertRaises(ValidationError):
            ForumCommentCreateSchema(body="x" * (MAX_COMMENT_LENGTH + 1))


class ForumResolveSchemaTests(unittest.TestCase):
    def test_defaults_to_closing_the_topic(self):
        parsed = ForumResolveSchema()
        self.assertTrue(parsed.is_resolved)
        self.assertIsNone(parsed.resolution_note)

    def test_blank_note_becomes_null(self):
        parsed = ForumResolveSchema(is_resolved=True, resolution_note="   ")
        self.assertIsNone(parsed.resolution_note)

    def test_reopen_is_allowed(self):
        parsed = ForumResolveSchema(is_resolved=False)
        self.assertFalse(parsed.is_resolved)


class ForumPagingTests(unittest.TestCase):
    def test_clamp_pagination(self):
        self.assertEqual(clamp_pagination(0, -5), (10, 0))
        self.assertEqual(clamp_pagination(500, 30), (50, 30))
        self.assertEqual(clamp_pagination(10, 20), (10, 20))

    def test_status_filter_falls_back_to_all(self):
        self.assertEqual(normalize_status_filter(None), "all")
        self.assertEqual(normalize_status_filter(" OPEN "), "open")
        self.assertEqual(normalize_status_filter("resolved"), "resolved")
        self.assertEqual(normalize_status_filter("unknown"), "all")


class ForumPhotoValidationTests(unittest.TestCase):
    def test_accepts_png_jpeg_and_webp(self):
        for content_type, data, name in (
            ("image/png", PNG_BYTES, "lastik.png"),
            ("image/jpeg", JPEG_BYTES, "lastik.jpg"),
            ("image/webp", WEBP_BYTES, "lastik.webp"),
        ):
            info = validate_photo(name, content_type, data)
            self.assertEqual(info["content_type"], content_type)
            self.assertEqual(info["file_size"], len(data))
            self.assertEqual(info["file_name"], name)

    def test_octet_stream_falls_back_to_the_extension(self):
        info = validate_photo("lastik.png", "application/octet-stream", PNG_BYTES)
        self.assertEqual(info["content_type"], "image/png")

    def test_non_image_type_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_photo("evrak.pdf", "application/pdf", PNG_BYTES)

    def test_signature_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_photo("sahte.png", "image/png", b"bu bir resim degil")

    def test_empty_file_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_photo("bos.png", "image/png", b"")

    def test_size_limit_is_enforced(self):
        oversized = PNG_BYTES + b"\x00" * MAX_PHOTO_BYTES
        with self.assertRaises(ValueError) as ctx:
            validate_photo("buyuk.png", "image/png", oversized)
        self.assertIn("5 MB", str(ctx.exception))

    def test_has_image_signature_is_strict(self):
        self.assertTrue(has_image_signature("image/png", PNG_BYTES))
        self.assertTrue(has_image_signature("image/webp", WEBP_BYTES))
        self.assertFalse(has_image_signature("image/png", WEBP_BYTES))
        self.assertFalse(has_image_signature("image/gif", PNG_BYTES))

    def test_file_name_is_sanitized(self):
        self.assertEqual(
            sanitize_file_name(r"C:\fotograflar\lastik.png"), "lastik.png"
        )
        self.assertEqual(sanitize_file_name("/tmp/foto.jpg"), "foto.jpg")
        self.assertEqual(sanitize_file_name(""), "foto.jpg")
        self.assertEqual(sanitize_file_name(None), "foto.jpg")

    def test_size_limit_matches_the_database_constraint(self):
        constraint = next(
            item
            for item in ForumTopicPhotoModel.__table__.constraints
            if getattr(item, "name", "") == "ck_forum_topic_photos_size_limit"
        )
        self.assertIn(str(MAX_PHOTO_BYTES), str(constraint.sqltext))
        self.assertEqual(MAX_PHOTOS_PER_TOPIC, 6)

    def test_inline_disposition_keeps_the_turkish_name(self):
        header = inline_disposition("Lastik fotoğrafı.jpg")
        self.assertTrue(header.startswith("inline; "))

        # The quoted fallback must stay ASCII; the real name travels in filename*.
        quoted = header.split('filename="', 1)[1].split('"', 1)[0]
        quoted.encode("ascii")
        self.assertIn(
            "filename*=UTF-8''Lastik%20foto%C4%9Fraf%C4%B1.jpg", header
        )

        # Quotes in the name would break the parameter, so they are replaced.
        self.assertIn('filename="kotu_ad.png"', inline_disposition('kotu"ad.png'))


class ForumTopicPermissionTests(unittest.TestCase):
    def test_author_can_close_own_topic_even_as_reader(self):
        self.assertTrue(can_manage_topic(user(status_id=4), 7))

    def test_manager_can_close_any_topic(self):
        self.assertTrue(can_manage_topic(user(status_id=2), 99))

    def test_other_reader_cannot_close(self):
        self.assertFalse(can_manage_topic(user(status_id=4), 99))

    def test_ensure_raises_403_for_other_reader(self):
        with self.assertRaises(HTTPException) as ctx:
            ensure_can_manage_topic(user(status_id=4), 99)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_missing_user_cannot_manage(self):
        self.assertFalse(can_manage_topic(None, None))


if __name__ == "__main__":
    unittest.main()

