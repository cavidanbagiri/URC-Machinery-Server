"""Offline regression tests for the Kiralık Makine (rented machine) table.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL.  They cover the write-schema validation,
the date-based status rule, the row-to-schema mapping (remaining/duration),
the SQL status filter and the route table.
"""

import unittest
import inspect
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
    compose_equipment_name,
    resolve_rental_status,
)
from repositories.rental_machine_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    UNKNOWN_TYPE_NAME,
    RentalMachineRepository,
    contains_condition,
    rental_status_condition,
    type_stats_statement,
)
from routers import rental_machine_router
from schemas.rental_machine_schemas import (
    MAX_COMPANY_NAME_LENGTH,
    MAX_PLATE_LENGTH,
    PaginatedRentalMachinesSchema,
    RentalMachineCreateSchema,
    RentalMachineItemSchema,
    RentalMachineTypeStatSchema,
    RentalMachineUpdateSchema,
)

ROW = namedtuple(
    "ROW",
    [
        "rental",
        "machine_type_name",
        "car_mark_name",
        "creator_firstname",
        "creator_lastname",
    ],
)


def payload(**overrides):
    data = {
        "machine_type_id": 4,
        "car_mark_id": 2,
        "plate_no": "34 ABC 123",
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
        "equipment_name": "Ekskavatör · CAT · 34 ABC 123",
        "machine_type_id": 4,
        "car_mark_id": 2,
        "plate_no": "34 ABC 123",
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


def row(rental_row=None, firstname=None, lastname=None, **names):
    """Build the ``_base_select`` row shape the repository maps."""

    rental_row = rental_row or rental()
    return ROW(
        rental_row,
        names.get("machine_type_name", "Ekskavatör"),
        names.get("car_mark_name", "CAT"),
        firstname,
        lastname,
    )


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

        self.assertEqual(parsed.machine_type_id, 4)
        self.assertEqual(parsed.car_mark_id, 2)
        self.assertEqual(parsed.plate_no, "34 ABC 123")
        self.assertEqual(parsed.start_date, date(2026, 11, 1))
        self.assertEqual(parsed.end_date, date(2026, 12, 31))

    def test_model_is_no_longer_a_payload_field(self):
        # The rental table shows a single Marka / Model column fed by the brand,
        # so the model link was dropped from the table and the API contract.
        self.assertNotIn("car_model_id", RentalMachineCreateSchema.model_fields)

        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(**payload(car_model_id=9))

    def test_names_collapse_repeated_whitespace(self):
        parsed = RentalMachineCreateSchema(
            **payload(
                plate_no="  34   ABC 123 ",
                company_name=" Ustay   Kiralama ",
                site_name=" Merkez  Şantiye ",
            )
        )

        self.assertEqual(parsed.plate_no, "34 ABC 123")
        self.assertEqual(parsed.company_name, "Ustay Kiralama")
        self.assertEqual(parsed.site_name, "Merkez Şantiye")

    def test_legacy_equipment_name_only_payload_is_accepted(self):
        data = payload()
        for field in ("machine_type_id", "car_mark_id", "plate_no"):
            data.pop(field)
        data["equipment_name"] = "  CAT   320D   Ekskavatör "

        parsed = RentalMachineCreateSchema(**data)

        self.assertEqual(parsed.equipment_name, "CAT 320D Ekskavatör")
        self.assertIsNone(parsed.machine_type_id)

    def test_blank_names_are_rejected(self):
        for field in ("equipment_name", "company_name", "site_name"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    RentalMachineCreateSchema(**payload(**{field: "   "}))

    def test_missing_company_and_site_are_rejected(self):
        for field in ("company_name", "site_name"):
            with self.subTest(field=field):
                data = payload()
                data.pop(field)
                with self.assertRaises(ValidationError):
                    RentalMachineCreateSchema(**data)

    def test_empty_equipment_is_rejected(self):
        data = payload()
        for field in ("machine_type_id", "car_mark_id", "plate_no"):
            data.pop(field)

        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(**data)

    def test_plate_only_whitespace_means_no_plate(self):
        data = payload()
        for field in ("machine_type_id", "car_mark_id"):
            data.pop(field)

        parsed = RentalMachineCreateSchema(**payload(plate_no="   "))

        self.assertIsNone(parsed.plate_no)
        # Still valid, because the machine type is set.
        self.assertEqual(parsed.machine_type_id, 4)

        data.pop("plate_no")
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(**data)

    def test_overlong_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(
                **payload(company_name="A" * (MAX_COMPANY_NAME_LENGTH + 1))
            )

    def test_overlong_plate_is_rejected(self):
        with self.assertRaises(ValidationError):
            RentalMachineCreateSchema(
                **payload(plate_no="A" * (MAX_PLATE_LENGTH + 1))
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
            equipment_name="Ekskavatör · CAT · 34 ABC 123",
            machine_type_name="Ekskavatör",
            car_mark_name="CAT",
            status=RENTAL_STATUS_ACTIVE,
            status_label="Aktif",
            days_remaining=10,
            duration_days=61,
        )

        self.assertEqual(item.status, "aktif")
        self.assertEqual(item.duration_days, 61)
        self.assertEqual(item.machine_type_name, "Ekskavatör")
        self.assertEqual(item.car_mark_name, "CAT")
        self.assertEqual(item.plate_no, "34 ABC 123")
        self.assertIsNone(item.created_by_name)
        self.assertNotIn("car_model_name", RentalMachineItemSchema.model_fields)

    def test_type_stat_schema_accepts_both_known_and_unknown_types(self):
        known = RentalMachineTypeStatSchema(
            type_id=4,
            type_name="Ekskavatör",
            total=3,
            active_count=2,
            planned_count=1,
            expired_count=0,
        )
        unknown = RentalMachineTypeStatSchema(
            type_name=UNKNOWN_TYPE_NAME,
            total=1,
            active_count=1,
            planned_count=0,
            expired_count=0,
        )

        self.assertEqual(known.type_id, 4)
        self.assertIsNone(unknown.type_id)

    def test_paginated_schema_defaults_to_no_items(self):
        page = PaginatedRentalMachinesSchema(total=0, limit=50, offset=0)

        self.assertEqual(page.items, [])
        self.assertEqual(page.type_stats, [])


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


class EquipmentLabelTests(unittest.TestCase):
    def test_all_parts_are_joined(self):
        self.assertEqual(
            compose_equipment_name(
                type_name="Ekskavatör",
                mark_name="CAT",
                plate_no="34 ABC 123",
            ),
            "Ekskavatör · CAT · 34 ABC 123",
        )

    def test_model_is_not_part_of_the_label(self):
        # The model column was dropped, so the helper no longer takes a model.
        with self.assertRaises(TypeError):
            compose_equipment_name(model_name="320D")

    def test_empty_parts_are_skipped(self):
        self.assertEqual(
            compose_equipment_name(type_name="Ekskavatör", plate_no="34 ABC 123"),
            "Ekskavatör · 34 ABC 123",
        )

    def test_parts_are_trimmed_and_collapsed(self):
        self.assertEqual(
            compose_equipment_name(type_name="  Ekskavatör ", mark_name=" CAT  "),
            "Ekskavatör · CAT",
        )

    def test_fallback_is_used_when_nothing_structured_is_set(self):
        self.assertEqual(
            compose_equipment_name(fallback="  CAT   320D  "),
            "CAT 320D",
        )

    def test_structured_fields_win_over_the_fallback(self):
        self.assertEqual(
            compose_equipment_name(type_name="Ekskavatör", fallback="CAT 320D"),
            "Ekskavatör",
        )


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

    def test_equipment_columns_are_optional(self):
        columns = MachineRentalModel.__table__.columns

        for field in (
            "machine_type_id",
            "car_mark_id",
            "plate_no",
        ):
            with self.subTest(field=field):
                self.assertTrue(columns[field].nullable)

    def test_model_column_was_dropped(self):
        self.assertNotIn("car_model_id", MachineRentalModel.__table__.columns)

    def test_equipment_lookups_use_set_null(self):
        expectations = {
            "machine_type_id": "type_transports",
            "car_mark_id": "car_marks",
        }

        for column, table in expectations.items():
            with self.subTest(column=column):
                foreign_key = next(
                    iter(MachineRentalModel.__table__.c[column].foreign_keys)
                )
                self.assertEqual(foreign_key.column.table.name, table)
                self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_plate_length_matches_the_schema(self):
        self.assertEqual(MachineRentalModel.__table__.c.plate_no.type.length, 50)

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
            row(rental(), "Ali", "Veli"),
            today=date(2026, 11, 22),
        )

        self.assertEqual(item["id"], 7)
        self.assertEqual(item["status"], RENTAL_STATUS_ACTIVE)
        self.assertEqual(item["status_label"], "Aktif")
        self.assertEqual(item["days_remaining"], 39)
        self.assertEqual(item["duration_days"], 61)
        self.assertEqual(item["created_by_name"], "Ali Veli")
        self.assertEqual(item["machine_type_id"], 4)
        self.assertEqual(item["machine_type_name"], "Ekskavatör")
        self.assertEqual(item["car_mark_name"], "CAT")
        self.assertEqual(item["plate_no"], "34 ABC 123")
        self.assertNotIn("car_model_name", item)

    def test_row_mapping_for_a_planned_rental(self):
        item = self.repository._row_to_item(
            row(
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
            row(
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

    def test_row_mapping_keeps_legacy_rows_readable(self):
        item = self.repository._row_to_item(
            row(
                rental(
                    machine_type_id=None,
                    car_mark_id=None,
                    plate_no=None,
                    equipment_name="CAT 320D Ekskavatör",
                ),
                None,
                None,
                machine_type_name=None,
                car_mark_name=None,
            ),
            today=date(2026, 11, 22),
        )

        self.assertEqual(item["equipment_name"], "CAT 320D Ekskavatör")
        self.assertIsNone(item["machine_type_id"])
        self.assertIsNone(item["machine_type_name"])

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

    def test_search_matches_the_label_and_free_text_columns(self):
        filters = self.repository._filters(search="  cat ")

        sql = compile_sql(filters[0])

        for column in (
            "equipment_name",
            "company_name",
            "site_name",
            "plate_no",
        ):
            self.assertIn(column, sql)
        self.assertIn("%cat%", sql)

    def test_empty_search_adds_no_filter(self):
        self.assertEqual(self.repository._filters(search="   "), [])

    def test_contains_condition_is_empty_for_blank_values(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIsNone(
                    contains_condition(MachineRentalModel.plate_no, value)
                )

    def test_company_and_site_filters_use_ilike(self):
        filters = self.repository._filters(company="ustay", site="merkez")

        self.assertEqual(2, len(filters))
        self.assertIn("company_name ILIKE", compile_sql(filters[0]))
        self.assertIn("%ustay%", compile_sql(filters[0]))
        self.assertIn("site_name ILIKE", compile_sql(filters[1]))
        self.assertIn("%merkez%", compile_sql(filters[1]))

    def test_lookup_filters_select_the_foreign_keys(self):
        filters = self.repository._filters(
            machine_type_id=4,
            car_mark_id=2,
        )

        self.assertEqual(2, len(filters))
        self.assertIn("machine_type_id = 4", compile_sql(filters[0]))
        self.assertIn("car_mark_id = 2", compile_sql(filters[1]))

    def test_model_is_not_a_filter_anymore(self):
        with self.assertRaises(TypeError):
            self.repository._filters(car_model_id=9)

    def test_date_range_filters_are_inclusive(self):
        filters = self.repository._filters(
            start_from=date(2026, 11, 1),
            start_to=date(2026, 11, 30),
            end_from=date(2026, 12, 1),
            end_to=date(2026, 12, 31),
        )

        sql = [compile_sql(condition) for condition in filters]

        self.assertIn("start_date >= '2026-11-01'", sql[0])
        self.assertIn("start_date <= '2026-11-30'", sql[1])
        self.assertIn("end_date >= '2026-12-01'", sql[2])
        self.assertIn("end_date <= '2026-12-31'", sql[3])

    def test_type_stats_statement_groups_by_machine_type(self):
        sql = compile_sql(type_stats_statement([], date(2026, 11, 22)))

        self.assertIn("GROUP BY", sql)
        self.assertIn("type_transports", sql)
        self.assertIn("count(machine_rentals.id)", sql)
        self.assertIn("CASE", sql)
        self.assertIn("active_count", sql)

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

    def test_list_endpoint_accepts_the_column_filters(self):
        signature = inspect.signature(
            rental_machine_router.fetch_rental_machines
        )
        parameters = set(signature.parameters)

        for name in (
            "machine_type_id",
            "car_mark_id",
            "plate",
            "company",
            "site",
            "start_from",
            "start_to",
            "end_from",
            "end_to",
        ):
            with self.subTest(parameter=name):
                self.assertIn(name, parameters)

        # The merged Marka / Model column only needs the brand filter.
        self.assertNotIn("car_model_id", parameters)

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
