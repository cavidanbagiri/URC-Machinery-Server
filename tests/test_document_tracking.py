"""Offline regression tests for the Evrak Takip Tablosu.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They check the date payload contract and
that the model, schema and repository constants stay in sync.
"""

import unittest
from datetime import date

from pydantic import ValidationError
from sqlalchemy import Date

from models.document_tracking_model import (
    DOCUMENT_DATE_FIELDS,
    MachineDocumentTrackingModel,
)
from schemas.document_tracking_schemas import (
    DocumentTrackingItemSchema,
    DocumentTrackingUpdateSchema,
)


def full_payload(value="2027-05-20"):
    return {field: value for field in DOCUMENT_DATE_FIELDS}


class DocumentTrackingSchemaTests(unittest.TestCase):
    def test_all_document_dates_are_optional(self):
        parsed = DocumentTrackingUpdateSchema()

        for field in DOCUMENT_DATE_FIELDS:
            self.assertIsNone(getattr(parsed, field))

    def test_all_document_dates_are_parsed(self):
        parsed = DocumentTrackingUpdateSchema(**full_payload())

        for field in DOCUMENT_DATE_FIELDS:
            self.assertEqual(getattr(parsed, field), date(2027, 5, 20))

    def test_null_clears_a_date(self):
        parsed = DocumentTrackingUpdateSchema(leasing_date=None)

        self.assertIsNone(parsed.leasing_date)

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            DocumentTrackingUpdateSchema(leasing_date="20-05-2027")

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            DocumentTrackingUpdateSchema(machine_id=10)

    def test_schema_fields_match_the_model_constant(self):
        self.assertEqual(
            set(DOCUMENT_DATE_FIELDS),
            set(DocumentTrackingUpdateSchema.model_fields),
        )

    def test_model_has_exactly_the_documented_date_columns(self):
        columns = MachineDocumentTrackingModel.__table__.columns

        self.assertEqual(len(DOCUMENT_DATE_FIELDS), 8)
        for field in DOCUMENT_DATE_FIELDS:
            self.assertIn(field, columns)
            self.assertIsInstance(columns[field].type, Date)

    def test_item_schema_keeps_machine_and_lookup_labels(self):
        item = DocumentTrackingItemSchema(
            machine_id=12,
            identification_no="TRK-012",
            plate_no="90 AB 123",
            territory_name="Merkez Şantiye",
            type_name="Ekskavatör",
            car_mark_name="CAT",
            car_model_name="320D",
            **full_payload(),
        )

        self.assertEqual(item.machine_id, 12)
        self.assertEqual(item.identification_no, "TRK-012")
        self.assertEqual(item.territory_name, "Merkez Şantiye")
        self.assertEqual(
            item.full_technical_inspection_date, date(2027, 5, 20)
        )


if __name__ == "__main__":
    unittest.main()
