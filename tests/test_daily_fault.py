"""Offline regression tests for daily (quick) fault rules.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover request validation, the PDF
guard rails and the Content-Disposition header used when a paper is opened.
"""

import unittest

from pydantic import ValidationError

from models.daily_fault_model import MAX_DOCUMENT_BYTES
from repositories.daily_fault_repository import (
    clamp_pagination,
    content_disposition,
    sanitize_file_name,
    validate_document,
)
from schemas.daily_fault_schemas import DailyFaultCreateSchema, normalize_km_hour


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def payload(**overrides):
    data = {
        "machine_id": 7,
        "territory_id": 2,
        "repair_type_id": 3,
        "km_hour": "12 450 km",
        "fault_assignment": "Lastik patladı",
        "changed_parts": "",
    }
    data.update(overrides)
    return data


class DailyFaultCreateSchemaTests(unittest.TestCase):
    def test_accepts_and_normalizes_form_values(self):
        parsed = DailyFaultCreateSchema(**payload(km_hour="  350   saat "))
        self.assertEqual(parsed.km_hour, "350 saat")
        self.assertEqual(parsed.fault_assignment, "Lastik patladı")
        self.assertIsNone(parsed.changed_parts)  # blank textarea -> null

    def test_blank_km_hour_is_rejected(self):
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(km_hour="   "))

    def test_km_hour_length_is_limited(self):
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(km_hour="k" * 51))

    def test_notes_are_limited(self):
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(fault_assignment="x" * 4001))

    def test_ids_must_be_positive(self):
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(machine_id=0))
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(territory_id=0))
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(repair_type_id=0))

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            DailyFaultCreateSchema(**payload(status="tamirde"))


class KmHourHelperTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(normalize_km_hour(" 12\t450   km "), "12 450 km")

    def test_rejects_blank(self):
        with self.assertRaises(ValueError):
            normalize_km_hour(" \t ")


class DocumentValidationTests(unittest.TestCase):
    def test_accepts_pdf_and_strips_paths(self):
        info = validate_document(
            r"C:\Users\me\Evrak 1.pdf", "application/pdf", PDF_BYTES
        )
        self.assertEqual(info["file_name"], "Evrak 1.pdf")
        self.assertEqual(info["content_type"], "application/pdf")
        self.assertEqual(info["file_size"], len(PDF_BYTES))

    def test_accepts_browser_octet_stream_for_pdf_files(self):
        info = validate_document("evrak.pdf", "application/octet-stream", PDF_BYTES)
        self.assertEqual(info["content_type"], "application/pdf")

    def test_rejects_non_pdf_content_type(self):
        with self.assertRaisesRegex(ValueError, "Sadece PDF"):
            validate_document("photo.png", "image/png", PDF_BYTES)

    def test_rejects_pdf_extension_with_fake_bytes(self):
        with self.assertRaisesRegex(ValueError, "geçerli bir PDF"):
            validate_document("fake.pdf", "application/pdf", b"not a pdf")

    def test_rejects_empty_file(self):
        with self.assertRaisesRegex(ValueError, "Boş dosya"):
            validate_document("empty.pdf", "application/pdf", b"")

    def test_rejects_oversized_file(self):
        oversized = b"%PDF-" + b"0" * MAX_DOCUMENT_BYTES
        with self.assertRaisesRegex(ValueError, "10 MB"):
            validate_document("big.pdf", "application/pdf", oversized)

    def test_sanitize_falls_back_to_default_name(self):
        self.assertEqual(sanitize_file_name(None), "evrak.pdf")
        self.assertEqual(sanitize_file_name("   "), "evrak.pdf")
        self.assertEqual(sanitize_file_name("/tmp/../x.pdf"), "x.pdf")


class ContentDispositionTests(unittest.TestCase):
    def test_inline_for_viewing(self):
        header = content_disposition("İş emri.pdf")
        self.assertTrue(header.startswith("inline;"))
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn("%C4%B0%C5%9F", header)  # İş

    def test_attachment_for_download(self):
        header = content_disposition("evrak.pdf", download=True)
        self.assertTrue(header.startswith("attachment;"))
        self.assertIn('filename="evrak.pdf"', header)

    def test_quotes_are_utf8_encoded(self):
        header = content_disposition('bad"name.pdf')
        self.assertIn("filename*=UTF-8''bad%22name.pdf", header)
        self.assertIn('filename="bad_name.pdf"', header)


class PaginationTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(clamp_pagination(0, -5), (20, 0))

    def test_upper_limit(self):
        self.assertEqual(clamp_pagination(500, 40), (100, 40))

    def test_keeps_valid_values(self):
        self.assertEqual(clamp_pagination(50, 100), (50, 100))


class DocumentLimitTests(unittest.TestCase):
    def test_model_and_repository_share_the_same_limit(self):
        from repositories import daily_fault_repository

        self.assertEqual(
            daily_fault_repository.MAX_DOCUMENT_BYTES, MAX_DOCUMENT_BYTES
        )
        self.assertEqual(MAX_DOCUMENT_BYTES, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
