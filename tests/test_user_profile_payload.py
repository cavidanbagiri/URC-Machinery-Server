"""Offline regression tests for the user payload behind the dashboard header.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not connect to PostgreSQL and do not touch S3.
"""

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from models.user_model import ImageModel
from repositories.auth_repository import serialize_user, user_image_url
from repositories.user_avatar_repository import UserAvatarRepository
from services.storage_service import (
    ALLOWED_IMAGE_TYPES,
    build_avatar_key,
    resolve_image_url,
)


def make_user(**overrides):
    data = {
        "id": 7,
        "firstname": "cavidan",
        "lastname": "hesenli",
        "email": "cavidan@example.com",
        "position": "Bakım Şefi",
        "image_id": 3,
        "image": SimpleNamespace(url="https://cdn.example.com/avatar.png"),
        "status_id": 1,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class SerializeUserTests(unittest.TestCase):
    def test_payload_includes_position_and_photo(self):
        user = make_user()

        payload = serialize_user(user, "Admin", user_image_url(user))

        self.assertEqual(payload["position"], "Bakım Şefi")
        self.assertEqual(payload["image_id"], 3)
        self.assertEqual(payload["image_url"], "https://cdn.example.com/avatar.png")
        self.assertEqual(payload["status_text"], "Admin")
        self.assertEqual(payload["username"], "cavidan hesenli")

    def test_missing_position_and_photo_fall_back_to_empty_strings(self):
        user = make_user(position=None, image_id=None, image=None)

        payload = serialize_user(user, "Viewer", user_image_url(user))

        self.assertEqual(payload["position"], "")
        self.assertIsNone(payload["image_id"])
        self.assertEqual(payload["image_url"], "")

    def test_register_payload_does_not_need_a_loaded_image(self):
        user = make_user(position=None, image_id=None)
        del user.image

        payload = serialize_user(user, "Viewer")

        self.assertEqual(payload["image_url"], "")
        self.assertEqual(payload["id"], 7)


class ResolveImageUrlTests(unittest.TestCase):
    def test_absolute_urls_are_returned_untouched(self):
        url = "https://cdn.example.com/path/avatar.webp"

        self.assertEqual(resolve_image_url(url), url)

    def test_blank_values_return_empty_string(self):
        self.assertEqual(resolve_image_url(None), "")
        self.assertEqual(resolve_image_url("   "), "")


class AvatarKeyTests(unittest.TestCase):
    def test_key_lives_under_the_user_prefix(self):
        key = build_avatar_key(42, "image/png")

        self.assertTrue(key.startswith("avatars/42/"))
        self.assertTrue(key.endswith(".png"))

    def test_every_upload_gets_a_new_key(self):
        self.assertNotEqual(
            build_avatar_key(1, "image/jpeg"),
            build_avatar_key(1, "image/jpeg"),
        )

    def test_extension_matches_type(self):
        for content_type, extension in ALLOWED_IMAGE_TYPES.items():
            self.assertTrue(build_avatar_key(7, content_type).endswith(extension))

    def test_unknown_type_falls_back_to_jpg(self):
        self.assertTrue(build_avatar_key(7, "application/pdf").endswith(".jpg"))


class _FakeSession:
    """Minimal ``AsyncSession`` stand-in for the pointer-swapping logic."""

    def __init__(self, user, images=None):
        self.user = user
        self.images = images or {}
        self.added = []
        self.committed = False
        self.rolled_back = False
        self._next_id = 90

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.user)

    async def get(self, _model, primary_key):
        return self.images.get(primary_key)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if obj.id is None:
                self._next_id += 1
                obj.id = self._next_id

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class UserAvatarRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_upload_creates_an_image_row(self):
        user = SimpleNamespace(id=7, image_id=None)
        session = _FakeSession(user)

        previous = await UserAvatarRepository(session).replace(7, "avatars/7/new.png")

        self.assertEqual(previous, "")
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].url, "avatars/7/new.png")
        self.assertEqual(user.image_id, session.added[0].id)
        self.assertTrue(session.committed)

    async def test_replacing_reuses_the_row_and_returns_the_old_key(self):
        image = ImageModel(url="avatars/7/old.png")
        image.id = 5
        user = SimpleNamespace(id=7, image_id=5)
        session = _FakeSession(user, {5: image})

        previous = await UserAvatarRepository(session).replace(7, "avatars/7/new.png")

        self.assertEqual(previous, "avatars/7/old.png")
        self.assertEqual(image.url, "avatars/7/new.png")
        self.assertEqual(session.added, [])
        self.assertEqual(user.image_id, 5)

    async def test_missing_user_is_a_404(self):
        session = _FakeSession(None)

        with self.assertRaises(HTTPException) as ctx:
            await UserAvatarRepository(session).replace(7, "avatars/7/new.png")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertFalse(session.committed)


if __name__ == "__main__":
    unittest.main()
