"""Offline regression tests for the dashboard team directory (avatar stack).

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not connect to PostgreSQL and do not touch S3.
"""

import unittest
from types import SimpleNamespace

from repositories.user_directory_repository import (
    build_team_member,
    clamp_team_limit,
)
from schemas.user_schemas import (
    DEFAULT_TEAM_LIMIT,
    MAX_TEAM_LIMIT,
    TeamDirectorySchema,
    TeamMemberSchema,
)


def make_user(**overrides):
    data = {
        "id": 7,
        "firstname": "  cavidan ",
        "lastname": "hesenli",
        "position": "Bakım Şefi",
        "image_id": 3,
        "image": SimpleNamespace(url="https://cdn.example.com/avatar.png"),
        "status_id": 1,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class BuildTeamMemberTests(unittest.TestCase):
    def test_payload_matches_the_stack_contract(self):
        member = build_team_member(
            make_user(),
            status_text="Admin",
            image_url="https://cdn.example.com/avatar.png",
            current_user_id=7,
        )

        self.assertEqual(member["full_name"], "cavidan hesenli")
        self.assertEqual(member["firstname"], "cavidan")
        self.assertEqual(member["position"], "Bakım Şefi")
        self.assertEqual(member["status_text"], "Admin")
        self.assertEqual(member["image_url"], "https://cdn.example.com/avatar.png")
        self.assertTrue(member["has_photo"])
        self.assertTrue(member["is_self"])

    def test_member_without_position_or_photo(self):
        member = build_team_member(
            make_user(position=None, image_id=None),
            status_text=None,
            image_url="",
            current_user_id=1,
        )

        self.assertEqual(member["position"], "")
        self.assertEqual(member["status_text"], "")
        self.assertEqual(member["image_url"], "")
        self.assertFalse(member["has_photo"])
        self.assertFalse(member["is_self"])

    def test_missing_names_do_not_leave_trailing_space(self):
        member = build_team_member(make_user(firstname="", lastname=""))

        self.assertEqual(member["full_name"], "")
        self.assertFalse(member["is_self"])

    def test_schema_accepts_the_built_payload(self):
        member = build_team_member(make_user(), status_text="Admin")

        parsed = TeamMemberSchema(**member)
        directory = TeamDirectorySchema(total=12, with_photo=4, items=[parsed])

        self.assertEqual(parsed.full_name, "cavidan hesenli")
        self.assertEqual(directory.total, 12)
        self.assertEqual(directory.with_photo, 4)


class ClampTeamLimitTests(unittest.TestCase):
    def test_default_when_missing(self):
        self.assertEqual(clamp_team_limit(None), DEFAULT_TEAM_LIMIT)

    def test_lower_and_upper_bounds(self):
        self.assertEqual(clamp_team_limit(0), 1)
        self.assertEqual(clamp_team_limit(-5), 1)
        self.assertEqual(clamp_team_limit(MAX_TEAM_LIMIT + 100), MAX_TEAM_LIMIT)

    def test_values_inside_the_range_are_kept(self):
        self.assertEqual(clamp_team_limit(6), 6)


if __name__ == "__main__":
    unittest.main()
