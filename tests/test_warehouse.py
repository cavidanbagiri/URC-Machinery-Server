"""Offline regression tests for the warehouse (ambar) module.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover the write schemas (trimming,
required fields, literals, quantity rules), the pure balance helper that keeps
the stock card and the ledger in sync, and the small query helpers.
"""

import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from models.warehouse_model import (
    MOVEMENT_IN,
    MOVEMENT_OUT,
    STOCK_STATUS_LOW,
    STOCK_STATUS_OK,
    STOCK_STATUS_OUT,
    movement_type_label,
    stock_status,
    stock_status_label,
)
from repositories.warehouse_repository import (
    MAX_LIMIT,
    apply_movement,
    build_search_pattern,
    clamp_pagination,
    machine_label,
    normalize_part_number,
    quantity_text,
    validate_movement_type,
)
from schemas.warehouse_schemas import (
    WarehouseItemCreateSchema,
    WarehouseItemUpdateSchema,
    WarehouseMovementCreateSchema,
    WarehouseReceiptCreateSchema,
)


def item_payload(**overrides):
    data = {
        "name": "  Yağ filtresi  ",
        "part_number": " 6ct-001 ",
        "description_tr": "  Yağ filtresi ",
        "description_ru": "  Масляный фильтр ",
        "unit": " Ad ",
        "territory_id": 3,
        "location": " A-12 ",
        "notes": "",
    }
    data.update(overrides)
    return data


def movement_payload(**overrides):
    data = {
        "item_id": 7,
        "movement_type": "GIRIS",
        "quantity": "2",
        "movement_date": "2026-10-31",
        "machine_id": 12,
        "document_no": " STF-2026-14 ",
        "note": "",
    }
    data.update(overrides)
    return data


class WarehouseItemCreateSchemaTests(unittest.TestCase):
    def test_normalizes_card_fields(self):
        parsed = WarehouseItemCreateSchema(**item_payload())

        self.assertEqual(parsed.name, "Yağ filtresi")
        self.assertEqual(parsed.part_number, "6ct-001")
        self.assertEqual(parsed.unit, "Ad")
        self.assertEqual(parsed.location, "A-12")
        self.assertIsNone(parsed.notes)  # blank text -> null
        self.assertEqual(parsed.min_quantity, Decimal("0"))

    def test_blank_name_and_unit_are_rejected(self):
        with self.assertRaises(ValidationError):
            WarehouseItemCreateSchema(**item_payload(name="   "))
        with self.assertRaises(ValidationError):
            WarehouseItemCreateSchema(**item_payload(unit=" "))

    def test_negative_critical_level_is_rejected(self):
        with self.assertRaises(ValidationError):
            WarehouseItemCreateSchema(**item_payload(min_quantity="-1"))

    def test_quantity_cannot_be_written_on_a_card(self):
        # The balance only moves through warehouse_movements.
        with self.assertRaises(ValidationError):
            WarehouseItemCreateSchema(**item_payload(quantity="5"))

    def test_part_number_is_optional(self):
        parsed = WarehouseItemCreateSchema(**item_payload(part_number=""))
        self.assertIsNone(parsed.part_number)


class WarehouseItemUpdateSchemaTests(unittest.TestCase):
    def test_only_sent_fields_are_updated(self):
        parsed = WarehouseItemUpdateSchema(min_quantity="4")
        self.assertEqual(
            parsed.model_dump(exclude_unset=True),
            {"min_quantity": Decimal("4")},
        )

    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            WarehouseItemUpdateSchema(name="  ")

    def test_blank_optional_text_becomes_none(self):
        parsed = WarehouseItemUpdateSchema(location="  ")
        self.assertIsNone(parsed.location)


class WarehouseMovementCreateSchemaTests(unittest.TestCase):
    def test_normalizes_type_quantity_and_texts(self):
        parsed = WarehouseMovementCreateSchema(**movement_payload())

        self.assertEqual(parsed.movement_type, MOVEMENT_IN)
        self.assertEqual(parsed.quantity, Decimal("2.000"))
        self.assertEqual(parsed.movement_date, date(2026, 10, 31))
        self.assertEqual(parsed.document_no, "STF-2026-14")
        self.assertIsNone(parsed.note)

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            WarehouseMovementCreateSchema(
                **movement_payload(movement_type="transfer")
            )

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            WarehouseMovementCreateSchema(**movement_payload(quantity="0"))
        with self.assertRaises(ValidationError):
            WarehouseMovementCreateSchema(**movement_payload(quantity="-3"))

    def test_date_is_required(self):
        payload = movement_payload()
        payload.pop("movement_date")
        with self.assertRaises(ValidationError):
            WarehouseMovementCreateSchema(**payload)


class WarehouseReceiptCreateSchemaTests(unittest.TestCase):
    def test_defaults_date_and_keeps_optional_quantity(self):
        parsed = WarehouseReceiptCreateSchema(
            items=[
                {"request_item_id": 4},
                {"request_item_id": 5, "quantity": "1.5"},
            ]
        )

        self.assertEqual(parsed.movement_date, date.today())
        self.assertIsNone(parsed.items[0].quantity)
        self.assertEqual(parsed.items[1].quantity, Decimal("1.500"))

    def test_at_least_one_row_is_required(self):
        with self.assertRaises(ValidationError):
            WarehouseReceiptCreateSchema(items=[])

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            WarehouseReceiptCreateSchema(
                items=[{"request_item_id": 4, "quantity": "0"}]
            )


class ApplyMovementTests(unittest.TestCase):
    def test_giris_adds_to_the_balance(self):
        self.assertEqual(
            apply_movement(Decimal("2.000"), MOVEMENT_IN, "1.5"),
            Decimal("3.500"),
        )

    def test_cikis_subtracts_from_the_balance(self):
        self.assertEqual(
            apply_movement(Decimal("5"), MOVEMENT_OUT, "2"),
            Decimal("3.000"),
        )

    def test_cikis_cannot_exceed_the_balance(self):
        with self.assertRaises(HTTPException) as raised:
            apply_movement(Decimal("1"), MOVEMENT_OUT, "2", "Yağ filtresi")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Yetersiz stok", raised.exception.detail)
        self.assertIn("Yağ filtresi", raised.exception.detail)

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            apply_movement(Decimal("1"), "transfer", "1")
        self.assertEqual(raised.exception.status_code, 400)

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(HTTPException):
            apply_movement(Decimal("1"), MOVEMENT_IN, "0")

    def test_balance_keeps_three_decimals(self):
        self.assertEqual(
            apply_movement(Decimal("0.1"), MOVEMENT_IN, "0.2"),
            Decimal("0.300"),
        )


class StockStatusTests(unittest.TestCase):
    def test_empty_card_is_out_of_stock(self):
        self.assertEqual(stock_status(0, 3), STOCK_STATUS_OUT)
        self.assertEqual(stock_status_label(STOCK_STATUS_OUT), "Stokta Yok")

    def test_at_or_below_critical_level(self):
        self.assertEqual(stock_status(3, 3), STOCK_STATUS_LOW)
        self.assertEqual(stock_status(1, 3), STOCK_STATUS_LOW)
        self.assertEqual(stock_status_label(STOCK_STATUS_LOW), "Kritik Seviye")

    def test_above_critical_level_is_healthy(self):
        self.assertEqual(stock_status(4, 3), STOCK_STATUS_OK)
        self.assertEqual(stock_status(1, 0), STOCK_STATUS_OK)
        self.assertEqual(stock_status_label(STOCK_STATUS_OK), "Yeterli")

    def test_movement_type_labels(self):
        self.assertEqual(movement_type_label("giris"), "Giriş")
        self.assertEqual(movement_type_label(" CIKIS "), "Çıkış")
        self.assertEqual(movement_type_label(None), "Hareket")


class HelperTests(unittest.TestCase):
    def test_part_numbers_are_compared_upper_case(self):
        self.assertEqual(normalize_part_number(" 6ct-001 "), "6CT-001")
        self.assertIsNone(normalize_part_number("   "))
        self.assertIsNone(normalize_part_number(None))

    def test_search_pattern_ignores_blank_input(self):
        self.assertIsNone(build_search_pattern("   "))
        self.assertEqual(build_search_pattern(" filtre "), "%filtre%")

    def test_pagination_is_clamped(self):
        self.assertEqual(clamp_pagination(0, -5), (20, 0))
        self.assertEqual(clamp_pagination(500, 40), (MAX_LIMIT, 40))

    def test_validate_movement_type(self):
        self.assertEqual(validate_movement_type(" GIRIS "), MOVEMENT_IN)
        with self.assertRaises(HTTPException) as raised:
            validate_movement_type("transfer")
        self.assertEqual(raised.exception.status_code, 400)

    def test_quantity_text_drops_trailing_zeros(self):
        self.assertEqual(quantity_text(Decimal("2.000")), "2")
        self.assertEqual(quantity_text(Decimal("2.500")), "2.5")

    def test_machine_label_falls_back_to_the_id(self):
        self.assertEqual(machine_label(None, None, None, 42), "Makine #42")
        self.assertEqual(machine_label(" 1001 ", None, None, 42), "1001")
        self.assertEqual(
            machine_label(None, "34 ABC 12", None, 42), "34 ABC 12"
        )


if __name__ == "__main__":
    unittest.main()
