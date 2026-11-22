"""Offline regression tests for the Kiralık Makine (rented machine) table.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL.  They cover the write-schema validation,
the date-based status rule, the row-to-schema mapping (remaining/duration),
the SQL status filter and the route table.
"""

import unittest
from collections import namedtuple
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Date
from sqlalchemy.dialects import postgresql

from models.rental_machine_model import (
    RENTAL_STATUS_ACTIVE,
    RENTAL_STATUS_EXPIRED,
    RENTAL_STATUS_LABELS,
    RENTAL_STATUS_PLANNED,
    RENTAL_STATUSES,
    MachineRentalModel,
    resolve_rental_status,
)
from repositories.rental_machine_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    RentalMachineRepository,
    rental_status_condition,
)
from routers import rental_machine_router
from schemas.rental_machine_schemas import (
    MAX_COMPANY_NAME_LENGTH,
    PaginatedRentalMachinesSchema,
    RentalMachineCreateSchema,
    RentalMachineItemSchema,
    RentalMachineUpdateSchema,
)

ROW = namedtuple("ROW", ["rental", "creator_firstname", "creator_lastname"])


def payload(**overrides):
    data = {
        "equipment_name": "CAT 320D Ekskavatör",
        "company_name": "Ustay Kiralama A.Ş.",
        "site_name": "Merkez Şantiye",
        "start_date": date(2026, 11, 1),
        "end_date": date(2026, 12, 31),
    }
    data.update(overrides)
    return data


def rental(**overrides):
    data = {
        "id": 7,
        "equipment_name": "CAT 320D Ekskavatör",
        "company_name": "Ustay Kiralama A.Ş.",
        "site_name": "Merkez Şantiye",
        "start_date": date(2026, 11, 1),
        "end_date": date(2026, 12, 31),
        "created_by_id": 3,
        "created_at": None,
        "updated_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def compile_sql(condition):
    return str(
        condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class RentalMachineSchemaTests(unittest.TestCase):
    def test_valid_payload_is_parsed(self):
        parsed = RentalMachineCreateSchema(**payload())

        self.assertEqual(parsed.equipment_name, "CAT 320D Ekskavatör")
        self.assertEqual(parsed.start_date, date(2026, 11, 1))
        self.assertEqual(parsed.end_date, date(2026, 12, 31))

    def test_names_collapse_repeated_whitespace(self):
        parsed = RentalMachineCreateSchema(
            **payload(
                equipment_name="  CAT   320D   Ekskavatör ",
                company_name=" Ustay   Kiralama ",
                site_name=" Merkez  Şantiye ",
            )
        )

        self.assertEqual(parsed.equipment_name, "CAT 320D Ekskavatör")
        self.assertEqual(parsed.company_name, "Ustay Kiralama")
        self.assertEqual(parsed.site_name, "Merkez Şantiye")

    def test_blank_names_are_rejected(self):
        for field in ("equipment_name", "company_name", "site_name"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    RentalMachineCreateSchema(**payload(**{field: "   "}))

    def test_missing_name_is_rejected(self):
        for field in ("equipment_name", "company_name", "site_name"):
            with self.subTest(field=field):
                data = payload()
                data.pop(field)
                with self.assertRaises(ValidationError):
                    RentalMachineCreateSchema(**data)

    def test_overlong_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(
                **payload(company_name="A" * (MAX_COMPANY_NAME_LENGTH + 1))
            )

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(
                **payload(
                    start_date=date(2027, 1, 1),
                    end_date=date(2026, 12, 31),
                )
            )

    def test_single_day_rental_is_allowed(self):
        parsed = RentalMachineCreateSchema(
            **payload(
                start_date=date(2026, 11, 20),
                end_date=date(2026, 11, 20),
            )
        )

        self.assertEqual(parsed.start_date, parsed.end_date)

    def test_dates_are_parsed_from_iso_strings(self):
        parsed = RentalMachineCreateSchema(
            **payload(start_date="2026-11-20", end_date="2026-11-25")
        )

        self.assertEqual(parsed.start_date, date(2026, 11, 20))
        self.assertEqual(parsed.end_date, date(2026, 11, 25))

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(**payload(start_date="20.11.2026"))

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(**payload(status="aktif"))

    def test_update_schema_shares_the_same_rules(self):
        parsed = RentalMachineUpdateSchema(**payload())
        self.assertEqual(parsed.site_name, "Merkez Şantiye")

        with self.assertRaises(ValidationError):
            RentalMachineUpdateSchema(
                **payload(
                    start_date=date(2027, 1, 1),
                    end_date=date(2026, 12, 31),
                )
            )

    def test_item_schema_accepts_the_mapped_row(self):
        item = RentalMachineItemSchema(
            id=7,
            **payload(),
            status=RENTAL_STATUS_ACTIVE,
            status_label="Aktif",
            days_remaining=10,
            duration_days=61,
        )

        self.assertEqual(item.status, "aktif")
        self.assertEqual(item.duration_days, 61)
        self.assertIsNone(item.created_by_name)

    def test_paginated_schema_defaults_to_no_items(self):
        page = PaginatedRentalMachinesSchema(total=0, limit=50, offset=0)

        self.assertEqual(page.items, [])


class RentalStatusRuleTests(unittest.TestCase):
    def test_future_start_is_planned(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 12, 1),
                date(2026, 12, 31),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_PLANNED,
        )

    def test_today_inside_the_range_is_active(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 11, 1),
                date(2026, 12, 31),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_ACTIVE,
        )

    def test_start_day_is_active(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 11, 22),
                date(2026, 12, 31),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_ACTIVE,
        )

    def test_end_day_is_still_active(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 11, 1),
                date(2026, 11, 22),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_ACTIVE,
        )

    def test_day_after_end_is_expired(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 11, 1),
                date(2026, 11, 21),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_EXPIRED,
        )

    def test_single_day_rental_is_active_on_that_day(self):
        self.assertEqual(
            resolve_rental_status(
                date(2026, 11, 22),
                date(2026, 11, 22),
                today=date(2026, 11, 22),
            ),
            RENTAL_STATUS_ACTIVE,
        )

    def test_every_status_has_a_label(self):
        self.assertEqual(set(RENTAL_STATUSES), set(RENTAL_STATUS_LABELS))
        self.assertEqual(
            set(RENTAL_STATUSES),
            {
                RENTAL_STATUS_ACTIVE,
                RENTAL_STATUS_PLANNED,
                RENTAL_STATUS_EXPIRED,
            },
        )
        self.assertEqual(RENTAL_STATUS_LABELS[RENTAL_STATUS_ACTIVE], "Aktif")


class RentalMachineModelTests(unittest.TestCase):
    def test_table_name(self):
        self.assertEqual(MachineRentalModel.__tablename__, "machine_rentals")

    def test_required_columns_are_not_nullable(self):
        columns = MachineRentalModel.__table__.columns

        for field in (
            "equipment_name",
            "company_name",
            "site_name",
            "start_date",
            "end_date",
        ):
            with self.subTest(field=field):
                self.assertFalse(columns[field].nullable)

    def test_dates_use_the_date_type(self):
        columns = MachineRentalModel.__table__.columns

        self.assertIsInstance(columns.start_date.type, Date)
        self.assertIsInstance(columns.end_date.type, Date)

    def test_date_order_check_constraint_exists(self):
        names = {
            constraint.name
            for constraint in MachineRentalModel.__table__.constraints
        }

        self.assertIn("ck_machine_rentals_date_order", names)

    def test_creator_is_cleared_with_the_user(self):
        foreign_key = next(
            iter(MachineRentalModel.__table__.c.created_by_id.foreign_keys)
        )

        self.assertEqual(foreign_key.column.table.name, "users")
        self.assertEqual(foreign_key.ondelete, "SET NULL")


class RentalMachineRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repository = RentalMachineRepository(db=None)

    def test_row_mapping_for_an_active_rental(self):
        item = self.repository._row_to_item(
            ROW(rental(), "Ali", "Veli"),
            today=date(2026, 11, 22),
        )

        self.assertEqual(item["id"], 7)
        self.assertEqual(item["status"], RENTAL_STATUS_ACTIVE)
        self.assertEqual(item["status_label"], "Aktif")
        self.assertEqual(item["days_remaining"], 39)
        self.assertEqual(item["duration_days"], 61)
        self.assertEqual(item["created_by_name"], "Ali Veli")

    def test_row_mapping_for_a_planned_rental(self):
        item = self.repository._row_to_item(
            ROW(
                rental(
                    start_date=date(2026, 12, 1),
                    end_date=date(2026, 12, 10),
                ),
                None,
                None,
            ),
            today=date(2026, 11, 22),
        )

        self.assertEqual(item["status"], RENTAL_STATUS_PLANNED)
        self.assertEqual(item["status_label"], "Planlandı")
        self.assertEqual(item["days_remaining"], 18)
        self.assertIsNone(item["created_by_name"])

    def test_row_mapping_for_an_expired_rental(self):
        item = self.repository._row_to_item(
            ROW(
                rental(
                    start_date=date(2026, 10, 1),
                    end_date=date(2026, 11, 20),
                ),
                "Ayşe",
                "",
            ),
            today=date(2026, 11, 22),
        )

        self.assertEqual(item["status"], RENTAL_STATUS_EXPIRED)
        self.assertEqual(item["status_label"], "Süresi doldu")
        self.assertEqual(item["days_remaining"], -2)
        self.assertEqual(item["created_by_name"], "Ayşe")

    def test_status_filter_for_planned_rentals(self):
        sql = compile_sql(
            rental_status_condition(RENTAL_STATUS_PLANNED, date(2026, 11, 22))
        )

        self.assertIn("start_date >", sql)
        self.assertNotIn("end_date", sql)

    def test_status_filter_for_expired_rentals(self):
        sql = compile_sql(
            rental_status_condition(RENTAL_STATUS_EXPIRED, date(2026, 11, 22))
        )

        self.assertIn("end_date <", sql)
        self.assertNotIn("start_date", sql)

    def test_status_filter_for_active_rentals(self):
        sql = compile_sql(
            rental_status_condition(RENTAL_STATUS_ACTIVE, date(2026, 11, 22))
        )

        self.assertIn("start_date <=", sql)
        self.assertIn("end_date >=", sql)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.repository._filters(status="beklemede")

        self.assertEqual(raised.exception.status_code, 400)

    def test_search_matches_all_three_text_columns(self):
        filters = self.repository._filters(search="  cat ")

        sql = compile_sql(filters[0])

        for column in ("equipment_name", "company_name", "site_name"):
            self.assertIn(column, sql)
        self.assertIn("%cat%", sql)

    def test_empty_search_adds_no_filter(self):
        self.assertEqual(self.repository._filters(search="   "), [])

    def test_pagination_limits(self):
        self.assertEqual(DEFAULT_LIMIT, 50)
        self.assertEqual(MAX_LIMIT, 100)


class RentalMachineRouterTests(unittest.TestCase):
    def test_routes_are_registered(self):
        routes = {
            (route.path, tuple(sorted(route.methods)))
            for route in rental_machine_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/fetch_rental_machines", ("GET",)), routes)
        self.assertIn(("/create", ("POST",)), routes)
        self.assertIn(("/update/{rental_id}", ("PUT",)), routes)
        self.assertIn(("/delete/{rental_id}", ("DELETE",)), routes)

    def test_create_returns_201_and_delete_204(self):
        statuses = {
            (route.path, route.status_code)
            for route in rental_machine_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/create", 201), statuses)
        self.assertIn(("/delete/{rental_id}", 204), statuses)


if __name__ == "__main__":
    unittest.main()
