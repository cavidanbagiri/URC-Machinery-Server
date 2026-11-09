"""Offline regression tests for the tire (lastik) module.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover request validation, the shared
PDF guard rails and the position matching used by the "eski kayıtlar" history.
"""

import unittest
from datetime import date, timedelta

from pydantic import ValidationError

from models.daily_fault_model import MAX_DOCUMENT_BYTES
from models.tire_model import MAX_TIRE_DOCUMENT_BYTES
from repositories.pdf_documents import MAX_PDF_BYTES, validate_document
from repositories.tire_repository import (
    clamp_pagination,
    content_disposition,
    position_matches,
    sanitize_file_name,
)
from schemas.tire_schemas import TireChangeCreateSchema, normalize_position


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def payload(**overrides):
    data = {
        "machine_id": 7,
        "position": "Sol Ön",
        "brand_model": "Michelin XZL",
        "size": "315/80 R22.5",
        "change_reason": "Patladı",
        "km_hour": "12 450 km",
        "change_date": date.today(),
    }
    data.update(overrides)
    return data


class TireChangeCreateSchemaTests(unittest.TestCase):
    def test_accepts_and_normalizes_form_values(self):
        parsed = TireChangeCreateSchema(
            **payload(position="  Sol   Ön ", change_reason="  Patladı  ")
        )
        self.assertEqual(parsed.position, "Sol Ön")
        self.assertEqual(parsed.change_reason, "Patladı")

    def test_blank_optional_text_becomes_none(self):
        parsed = TireChangeCreateSchema(**payload(brand_model="   ", size=""))
        self.assertIsNone(parsed.brand_model)
        self.assertIsNone(parsed.size)

    def test_blank_position_is_rejected(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(position="   "))

    def test_position_length_is_limited(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(position="L" * 51))

    def test_brand_model_length_is_limited(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(brand_model="M" * 151))

    def test_reason_length_is_limited(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(change_reason="x" * 1001))

    def test_machine_id_must_be_positive(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(machine_id=0))

    def test_future_change_date_is_rejected(self):
        tomorrow = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(change_date=tomorrow))

    def test_change_date_may_be_omitted(self):
        data = payload()
        data.pop("change_date")
        self.assertIsNone(TireChangeCreateSchema(**data).change_date)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            TireChangeCreateSchema(**payload(previous_count=2))


class PositionHelperTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(normalize_position("  Sol\tArka   1 "), "Sol Arka 1")

    def test_rejects_blank(self):
        with self.assertRaises(ValueError):
            normalize_position(" \t ")

    def test_match_is_case_insensitive_and_trimmed(self):
        expr = position_matches(None, "  sol   ÖN  ")
        # The stored side is lower-cased in SQL; the typed side is normalized here.
        self.assertEqual(expr.right.value, "sol ön")


class TireDocumentValidationTests(unittest.TestCase):
    def test_accepts_pdf_and_strips_paths(self):
        info = validate_document(
            r"C:\Users\me\Lastik Faturası.pdf",
            "application/pdf",
            PDF_BYTES,
            max_bytes=MAX_TIRE_DOCUMENT_BYTES,
        )
        self.assertEqual(info["file_name"], "Lastik Faturası.pdf")
        self.assertEqual(info["content_type"], "application/pdf")
        self.assertEqual(info["file_size"], len(PDF_BYTES))

    def test_rejects_non_pdf_content_type(self):
        with self.assertRaisesRegex(ValueError, "Sadece PDF"):
            validate_document("photo.png", "image/png", PDF_BYTES)

    def test_rejects_fake_pdf_bytes(self):
        with self.assertRaisesRegex(ValueError, "geçerli bir PDF"):
            validate_document("fake.pdf", "application/pdf", b"not a pdf")

    def test_rejects_oversized_file(self):
        oversized = b"%PDF-" + b"0" * MAX_TIRE_DOCUMENT_BYTES
        with self.assertRaisesRegex(ValueError, "10 MB"):
            validate_document(
                "big.pdf",
                "application/pdf",
                oversized,
                max_bytes=MAX_TIRE_DOCUMENT_BYTES,
            )

    def test_sanitize_reuses_the_shared_fallback_name(self):
        self.assertEqual(sanitize_file_name(None), "evrak.pdf")
        self.assertEqual(sanitize_file_name("/tmp/../x.pdf"), "x.pdf")


class ContentDispositionTests(unittest.TestCase):
    def test_attachment_for_download(self):
        header = content_disposition("Lastik Faturası.pdf", download=True)
        self.assertTrue(header.startswith("attachment;"))
        self.assertIn("filename*=UTF-8''", header)


class PaginationTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(clamp_pagination(0, -5), (20, 0))

    def test_upper_limit(self):
        self.assertEqual(clamp_pagination(500, 40), (100, 40))


class DocumentLimitTests(unittest.TestCase):
    def test_module_limits_are_identical(self):
        # daily faults, tire changes and the shared PDF module must agree.
        self.assertEqual(MAX_TIRE_DOCUMENT_BYTES, MAX_DOCUMENT_BYTES)
        self.assertEqual(MAX_PDF_BYTES, MAX_TIRE_DOCUMENT_BYTES)
        self.assertEqual(MAX_TIRE_DOCUMENT_BYTES, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
