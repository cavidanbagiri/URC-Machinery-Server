"""Offline regression tests for the simple stock module.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover the write schemas, the
quantity helper that keeps the card balance non-negative, and the small query
helpers used by the repository.
"""

import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from models.stock_model import quantize_quantity
from repositories.stock_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    StockRepository,
    apply_stock_out,
    build_search_pattern,
    clamp_pagination,
    machine_label,
    quantity_text,
)
from schemas.stock_schemas import (
    StockIssueCreateSchema,
    StockItemCreateSchema,
    StockItemUpdateSchema,
)


def item_payload(**overrides):
    data = {
        "name": "  Yağ filtresi  ",
        "unit": " Ad ",
        "quantity": "5",
        "notes": "",
    }
    data.update(overrides)
    return data


def issue_payload(**overrides):
    data = {
        "stock_item_id": 7,
        "quantity": "2.5",
        "issue_date": "2026-11-17",
        "machine_id": 12,
        "given_to": "  Mehmet usta  ",
        "note": "",
    }
    data.update(overrides)
    return data


class StockItemCreateSchemaTests(unittest.TestCase):
    def test_normalizes_card_fields(self):
        parsed = StockItemCreateSchema(**item_payload())

        self.assertEqual(parsed.name, "Yağ filtresi")
        self.assertEqual(parsed.unit, "Ad")
        self.assertEqual(parsed.quantity, Decimal("5"))
        self.assertIsNone(parsed.notes)  # blank text -> null

    def test_quantity_defaults_to_zero(self):
        payload = item_payload()
        payload.pop("quantity")
        self.assertEqual(
            StockItemCreateSchema(**payload).quantity, Decimal("0")
        )

    def test_blank_name_and_unit_are_rejected(self):
        with self.assertRaises(ValidationError):
            StockItemCreateSchema(**item_payload(name="   "))
        with self.assertRaises(ValidationError):
            StockItemCreateSchema(**item_payload(unit=" "))

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            StockItemCreateSchema(**item_payload(quantity="-1"))

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            StockItemCreateSchema(**item_payload(part_number="ABC"))


class StockItemUpdateSchemaTests(unittest.TestCase):
    def test_only_sent_fields_are_updated(self):
        parsed = StockItemUpdateSchema(quantity="3")

        self.assertEqual(parsed.quantity, Decimal("3"))
        self.assertIsNone(parsed.name)
        self.assertIsNone(parsed.unit)
        self.assertEqual(parsed.model_dump(exclude_unset=True), {
            "quantity": Decimal("3"),
        })

    def test_blank_text_is_rejected_when_present(self):
        with self.assertRaises(ValidationError):
            StockItemUpdateSchema(name="  ")

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            StockItemUpdateSchema(quantity="-0.001")


class StockIssueCreateSchemaTests(unittest.TestCase):
    def test_normalizes_issue_fields(self):
        parsed = StockIssueCreateSchema(**issue_payload())

        self.assertEqual(parsed.quantity, Decimal("2.5"))
        self.assertEqual(parsed.given_to, "Mehmet usta")
        self.assertIsNone(parsed.note)
        self.assertEqual(parsed.issue_date.isoformat(), "2026-11-17")

    def test_machine_is_optional(self):
        parsed = StockIssueCreateSchema(**issue_payload(machine_id=None))
        self.assertIsNone(parsed.machine_id)

    def test_zero_or_negative_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            StockIssueCreateSchema(**issue_payload(quantity="0"))
        with self.assertRaises(ValidationError):
            StockIssueCreateSchema(**issue_payload(quantity="-2"))

    def test_issue_date_is_required(self):
        payload = issue_payload()
        payload.pop("issue_date")
        with self.assertRaises(ValidationError):
            StockIssueCreateSchema(**payload)


class StockOutTests(unittest.TestCase):
    def test_subtracts_and_keeps_three_decimals(self):
        self.assertEqual(
            apply_stock_out(Decimal("5"), "2"),
            Decimal("3.000"),
        )
        self.assertEqual(
            apply_stock_out(Decimal("0.300"), "0.2"),
            Decimal("0.100"),
        )

    def test_can_empty_the_card(self):
        self.assertEqual(
            apply_stock_out(Decimal("2.5"), "2.5"),
            Decimal("0.000"),
        )

    def test_more_than_the_balance_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            apply_stock_out(Decimal("1"), "2", "Yağ filtresi")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Yetersiz stok", raised.exception.detail)
        self.assertIn("Yağ filtresi", raised.exception.detail)

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            apply_stock_out(Decimal("1"), "0")
        self.assertEqual(raised.exception.status_code, 400)


class IssueFilterTests(unittest.TestCase):
    """Filtreler sorguya gerçekten ekleniyor mu? (regresyon)"""

    def setUp(self):
        # SQL ifadeleri kurmak veritabanına bağlanmaz.
        self.repository = StockRepository(None)

    def test_blank_filters_produce_no_conditions(self):
        conditions = self.repository._issue_conditions(
            search="   ",
            stock_item_id=None,
            machine_id=None,
            date_from=None,
            date_to=None,
        )
        self.assertEqual(conditions, [])

    def test_every_filter_is_returned(self):
        conditions = self.repository._issue_conditions(
            search="filtre",
            stock_item_id=7,
            machine_id=3,
            date_from=date(2026, 11, 1),
            date_to=date(2026, 11, 30),
        )
        self.assertEqual(len(conditions), 5)


class HelperTests(unittest.TestCase):
    def test_quantize_rounds_to_three_decimals(self):
        self.assertEqual(quantize_quantity("2.1234"), Decimal("2.123"))
        self.assertEqual(quantize_quantity(None), Decimal("0.000"))

    def test_quantity_text_drops_trailing_zeros(self):
        self.assertEqual(quantity_text(Decimal("2.000")), "2")
        self.assertEqual(quantity_text(Decimal("2.500")), "2.5")

    def test_search_pattern_ignores_blank_input(self):
        self.assertIsNone(build_search_pattern("   "))
        self.assertEqual(build_search_pattern(" filtre "), "%filtre%")

    def test_pagination_is_clamped(self):
        self.assertEqual(clamp_pagination(0, -5), (DEFAULT_LIMIT, 0))
        self.assertEqual(clamp_pagination(500, 40), (MAX_LIMIT, 40))

    def test_machine_label_prefers_identification_number(self):
        self.assertEqual(machine_label(" 1001 ", "34 ABC 12", None, 42), "1001")
        self.assertEqual(
            machine_label(None, "34 ABC 12", None, 42), "34 ABC 12"
        )
        self.assertEqual(machine_label(None, None, "VIN42", 42), "VIN42")
        self.assertEqual(machine_label(None, None, None, 42), "Makine #42")
        self.assertEqual(machine_label(None, None, None), "—")


if __name__ == "__main__":
    unittest.main()
