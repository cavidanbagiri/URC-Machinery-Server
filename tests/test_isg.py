"""Offline regression tests for the ISG (occupational safety) page.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL.  They cover the write-schema validation,
the fixed "Sorumlu" list, the PDF/photo evidence guard rails, the SRU/DCU stat
rule, the SQL filters and the route table.
"""

import asyncio
import unittest
from collections import namedtuple
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import LargeBinary, Text
from sqlalchemy.dialects import postgresql

from models.isg_model import (
    ISG_RESPONSIBLES,
    ISG_SEVERITIES,
    ISG_SEVERITY_CRITICAL,
    ISG_SEVERITY_DEFAULT,
    ISG_SEVERITY_LABELS,
    ISG_SEVERITY_LOW,
    ISG_STATUSES,
    ISG_STATUS_CLOSED,
    ISG_STATUS_LABELS,
    ISG_STATUS_OPEN,
    MAX_EVIDENCE_BYTES,
    IsgAttachmentModel,
    IsgNonconformityModel,
)
from repositories.isg_evidence import (
    MAX_EVIDENCE_BYTES as EVIDENCE_LIMIT,
    is_image_content_type,
    resolve_evidence_content_type,
    validate_evidence,
)
from repositories.isg_repository import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    IsgRepository,
    joined_names,
    summarize_overview,
    summarize_projects,
    summarize_severities,
)
from routers import isg_router
from schemas.isg_schemas import (
    IsgNonconformityCreateSchema,
    IsgNonconformityItemSchema,
    IsgProjectSeverityItemSchema,
    IsgProjectSummarySchema,
    IsgStatusUpdateSchema,
    canonical_responsible,
)

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def payload(**overrides):
    data = {
        "record_date": date(2026, 11, 22),
        "description": "SRU sahasında baret takılmıyor",
        "status": ISG_STATUS_OPEN,
        "severity": ISG_SEVERITY_DEFAULT,
        "territory_id": 3,
        "responsible_name": "Ramiz Khayramov",
    }
    data.update(overrides)
    return data


def compile_sql(condition):
    return str(
        condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class IsgSchemaTests(unittest.TestCase):
    def test_valid_payload_is_parsed_with_open_default(self):
        parsed = IsgNonconformityCreateSchema(**payload())

        self.assertEqual(parsed.record_date, date(2026, 11, 22))
        self.assertEqual(parsed.status, ISG_STATUS_OPEN)
        self.assertEqual(parsed.severity, ISG_SEVERITY_DEFAULT)
        self.assertEqual(parsed.territory_id, 3)

    def test_description_is_trimmed(self):
        parsed = IsgNonconformityCreateSchema(
            **payload(description="  Baret yok  ")
        )

        self.assertEqual(parsed.description, "Baret yok")

    def test_blank_description_is_rejected(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(description="   \n  "))

    def test_overlong_description_is_rejected(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(description="a" * 2001))

    def test_missing_record_date_is_rejected(self):
        data = payload()
        data.pop("record_date")

        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**data)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(status="beklemede"))

    def test_unknown_severity_is_rejected(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(severity="orta"))

    def test_every_severity_code_is_accepted(self):
        for code in ISG_SEVERITIES:
            with self.subTest(code=code):
                parsed = IsgNonconformityCreateSchema(**payload(severity=code))
                self.assertEqual(parsed.severity, code)

    def test_severity_is_optional_and_defaults_to_important(self):
        data = payload()
        data.pop("severity")

        parsed = IsgNonconformityCreateSchema(**data)

        self.assertEqual(parsed.severity, ISG_SEVERITY_DEFAULT)
        self.assertEqual(ISG_SEVERITY_DEFAULT, "onemli")

    def test_extra_field_is_forbidden(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(closed_at=None))

    def test_responsible_is_canonicalised_case_insensitively(self):
        parsed = IsgNonconformityCreateSchema(
            **payload(responsible_name="  imomjon   SHADYEV ")
        )

        self.assertEqual(parsed.responsible_name, "Imomjon Shadyev")

    def test_unknown_responsible_is_rejected(self):
        with self.assertRaises(ValidationError):
            IsgNonconformityCreateSchema(**payload(responsible_name="Ali Veli"))

    def test_blank_responsible_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_responsible("   ")

    def test_responsible_list_has_the_four_team_members(self):
        self.assertEqual(len(ISG_RESPONSIBLES), 4)
        self.assertIn("Mustafa Palta", ISG_RESPONSIBLES)
        self.assertIn("Andrey Stepanov", ISG_RESPONSIBLES)

    def test_territory_id_must_be_positive(self):
        for value in (0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    IsgNonconformityCreateSchema(**payload(territory_id=value))

    def test_status_update_schema_only_accepts_two_codes(self):
        self.assertEqual(
            IsgStatusUpdateSchema(status=ISG_STATUS_CLOSED).status,
            ISG_STATUS_CLOSED,
        )
        with self.assertRaises(ValidationError):
            IsgStatusUpdateSchema(status="tamam")

    def test_status_codes_and_labels_match(self):
        self.assertEqual(set(ISG_STATUSES), {ISG_STATUS_OPEN, ISG_STATUS_CLOSED})
        self.assertEqual(ISG_STATUS_LABELS[ISG_STATUS_OPEN], "Açık")
        self.assertEqual(ISG_STATUS_LABELS[ISG_STATUS_CLOSED], "Kapalı")

    def test_severity_codes_and_labels_match(self):
        self.assertEqual(
            set(ISG_SEVERITIES),
            {"kritik", "onemli", "az_onemli"},
        )
        self.assertEqual(ISG_SEVERITY_LABELS[ISG_SEVERITY_CRITICAL], "Kritik")
        self.assertEqual(ISG_SEVERITY_LABELS[ISG_SEVERITY_DEFAULT], "Önemli")
        self.assertEqual(ISG_SEVERITY_LABELS[ISG_SEVERITY_LOW], "Az Önemli")

    def test_item_schema_defaults_are_empty(self):
        item = IsgNonconformityItemSchema(
            id=1,
            record_date=date(2026, 11, 22),
            description="Baret yok",
            status=ISG_STATUS_OPEN,
            status_label="Açık",
            severity=ISG_SEVERITY_CRITICAL,
            severity_label="Kritik",
            territory_id=3,
            responsible_name="Ramiz Khayramov",
        )

        self.assertEqual(item.attachment_count, 0)
        self.assertEqual(item.attachments, [])
        self.assertEqual(item.severity_label, "Kritik")


class IsgEvidenceTests(unittest.TestCase):
    def test_pdf_is_accepted(self):
        result = validate_evidence("rapor.pdf", "application/pdf", PDF_BYTES)

        self.assertEqual(result["file_name"], "rapor.pdf")
        self.assertEqual(result["content_type"], "application/pdf")
        self.assertEqual(result["file_size"], len(PDF_BYTES))

    def test_jpeg_png_and_webp_are_accepted(self):
        cases = (
            ("foto.jpg", "image/jpeg", JPEG_BYTES),
            ("foto.png", "image/png", PNG_BYTES),
            ("foto.webp", "image/webp", WEBP_BYTES),
        )

        for name, content_type, data in cases:
            with self.subTest(content_type=content_type):
                result = validate_evidence(name, content_type, data)
                self.assertEqual(result["content_type"], content_type)

    def test_image_jpg_alias_is_normalised(self):
        result = validate_evidence("foto.jpg", "image/jpg", JPEG_BYTES)

        self.assertEqual(result["content_type"], "image/jpeg")

    def test_octet_stream_uses_the_extension(self):
        result = validate_evidence("foto.PNG", "application/octet-stream", PNG_BYTES)

        self.assertEqual(result["content_type"], "image/png")

    def test_octet_stream_without_known_extension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Sadece PDF veya fotoğraf"):
            validate_evidence("dosya.bin", "application/octet-stream", PNG_BYTES)

    def test_docx_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Sadece PDF veya fotoğraf"):
            validate_evidence("rapor.docx", "application/vnd.ms-word", b"PK\x03\x04")

    def test_empty_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Boş dosya"):
            validate_evidence("bos.pdf", "application/pdf", b"")

    def test_oversized_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "en fazla"):
            validate_evidence(
                "buyuk.pdf",
                "application/pdf",
                b"%PDF-" + b"0" * 64,
                max_bytes=32,
            )

    def test_fake_pdf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "geçerli bir PDF veya fotoğraf"):
            validate_evidence("sahte.pdf", "application/pdf", b"not a pdf")

    def test_content_type_and_signature_must_match(self):
        with self.assertRaisesRegex(ValueError, "geçerli bir PDF veya fotoğraf"):
            validate_evidence("foto.jpg", "image/jpeg", PDF_BYTES)

    def test_short_webp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "geçerli bir PDF veya fotoğraf"):
            validate_evidence("kisa.webp", "image/webp", b"RIFF\x00")

    def test_path_traversal_is_reduced_to_base_name(self):
        result = validate_evidence(
            "C:\\temp\\../rapor.pdf",
            "application/pdf",
            PDF_BYTES,
        )

        self.assertEqual(result["file_name"], "rapor.pdf")

    def test_unnamed_upload_gets_a_fallback_name(self):
        result = validate_evidence("", "application/pdf", PDF_BYTES)

        self.assertTrue(result["file_name"].endswith(".pdf"))

    def test_image_helper(self):
        self.assertTrue(is_image_content_type("image/png"))
        self.assertTrue(is_image_content_type("image/JPEG; charset=binary"))
        self.assertFalse(is_image_content_type("application/pdf"))
        self.assertFalse(is_image_content_type(None))

    def test_resolve_content_type_returns_canonical_value(self):
        self.assertEqual(
            resolve_evidence_content_type("x.pdf", "application/x-pdf"),
            "application/pdf",
        )

    def test_evidence_limit_matches_the_model(self):
        self.assertEqual(EVIDENCE_LIMIT, MAX_EVIDENCE_BYTES)
        self.assertEqual(MAX_EVIDENCE_BYTES, 10 * 1024 * 1024)


class IsgOverviewTests(unittest.TestCase):
    def test_counts_are_split_between_sru_dcu_and_totals(self):
        rows = [
            ("SRU", ISG_STATUS_OPEN, 3),
            ("SRU", ISG_STATUS_CLOSED, 2),
            ("DCU", ISG_STATUS_OPEN, 4),
            ("DCU", ISG_STATUS_CLOSED, 1),
            ("Ofis", ISG_STATUS_OPEN, 2),
            ("Ofis", ISG_STATUS_CLOSED, 1),
        ]

        overview = summarize_overview(rows)

        self.assertEqual(overview["total"], 13)
        self.assertEqual(overview["open_total"], 9)
        self.assertEqual(overview["closed_total"], 4)
        self.assertEqual(overview["sru_opened"], 5)
        self.assertEqual(overview["sru_open"], 3)
        self.assertEqual(overview["sru_closed"], 2)
        self.assertEqual(overview["dcu_opened"], 5)
        self.assertEqual(overview["dcu_open"], 4)
        self.assertEqual(overview["dcu_closed"], 1)
        self.assertEqual(overview["sites_closed_total"], 3)

    def test_site_name_matches_trimmed_and_case_insensitively(self):
        rows = [
            (" sru ", ISG_STATUS_OPEN, 2),
            ("Dcu", ISG_STATUS_CLOSED, 1),
        ]

        overview = summarize_overview(rows)

        self.assertEqual(overview["sru_opened"], 2)
        self.assertEqual(overview["dcu_closed"], 1)
        self.assertEqual(overview["sites_closed_total"], 1)

    def test_other_sites_only_reach_the_totals(self):
        overview = summarize_overview([("Merkez Şantiye", ISG_STATUS_CLOSED, 7)])

        self.assertEqual(overview["closed_total"], 7)
        self.assertEqual(overview["sru_closed"], 0)
        self.assertEqual(overview["dcu_closed"], 0)
        self.assertEqual(overview["sites_closed_total"], 0)

    def test_empty_rows_return_zeros(self):
        overview = summarize_overview([])

        for key, value in overview.items():
            with self.subTest(key=key):
                self.assertEqual(value, 0)

    def test_string_counts_are_cast_to_int(self):
        overview = summarize_overview([("SRU", ISG_STATUS_OPEN, "3")])

        self.assertEqual(overview["sru_open"], 3)
        self.assertIsInstance(overview["total"], int)


class IsgProjectSummaryTests(unittest.TestCase):
    def test_counts_are_grouped_per_project(self):
        rows = [
            (1, "SRU", ISG_STATUS_OPEN, 3),
            (1, "SRU", ISG_STATUS_CLOSED, 2),
            (2, "DCU", ISG_STATUS_OPEN, 4),
            (2, "DCU", ISG_STATUS_CLOSED, 1),
            (3, "Merkez Şantiye", ISG_STATUS_CLOSED, 5),
        ]

        summary = summarize_projects(rows)

        self.assertEqual(summary["project_count"], 3)
        self.assertEqual(summary["total"], 15)
        self.assertEqual(summary["open_total"], 7)
        self.assertEqual(summary["closed_total"], 8)

        by_id = {item["territory_id"]: item for item in summary["items"]}
        self.assertEqual(by_id[1]["open"], 3)
        self.assertEqual(by_id[1]["closed"], 2)
        self.assertEqual(by_id[1]["total"], 5)
        self.assertEqual(by_id[2]["open"], 4)
        self.assertEqual(by_id[2]["closed"], 1)
        self.assertEqual(by_id[3]["open"], 0)
        self.assertEqual(by_id[3]["closed"], 5)

    def test_items_are_sorted_by_open_then_total_then_name(self):
        rows = [
            (1, "SRU", ISG_STATUS_OPEN, 2),
            (1, "SRU", ISG_STATUS_CLOSED, 6),
            (2, "DCU", ISG_STATUS_OPEN, 2),
            (2, "DCU", ISG_STATUS_CLOSED, 1),
            (3, "Merkez", ISG_STATUS_CLOSED, 1),
        ]

        names = [item["territory_name"] for item in summarize_projects(rows)["items"]]

        # SRU and DCU have 2 open each; SRU has the bigger total, then the
        # project with nothing open closes the list.
        self.assertEqual(names, ["SRU", "DCU", "Merkez"])

    def test_project_name_is_trimmed_and_blank_falls_back(self):
        rows = [
            (1, "  SRU  ", ISG_STATUS_OPEN, 1),
            (2, "   ", ISG_STATUS_CLOSED, 1),
        ]

        summary = summarize_projects(rows)

        self.assertEqual(summary["items"][0]["territory_name"], "SRU")
        self.assertEqual(summary["items"][1]["territory_name"], "—")

    def test_empty_rows_return_empty_items_and_zero_totals(self):
        summary = summarize_projects([])

        self.assertEqual(summary["items"], [])
        self.assertEqual(summary["project_count"], 0)
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["open_total"], 0)
        self.assertEqual(summary["closed_total"], 0)

    def test_string_counts_are_cast_to_int(self):
        summary = summarize_projects([(1, "SRU", ISG_STATUS_OPEN, "3")])

        item = summary["items"][0]
        self.assertEqual(item["open"], 3)
        self.assertEqual(item["total"], 3)
        self.assertIsInstance(summary["total"], int)

    def test_summary_matches_the_project_summary_schema(self):
        summary = summarize_projects(
            [(1, "SRU", ISG_STATUS_OPEN, 2), (1, "SRU", ISG_STATUS_CLOSED, 1)]
        )

        parsed = IsgProjectSummarySchema(**summary)

        self.assertEqual(parsed.project_count, 1)
        self.assertEqual(parsed.items[0].territory_name, "SRU")
        self.assertEqual(parsed.items[0].open, 2)
        self.assertEqual(parsed.items[0].closed, 1)
        # A response without the importance breakdown stays valid.
        self.assertEqual(parsed.severities, [])


class IsgSeveritySummaryTests(unittest.TestCase):
    """The Kritik / Önemli / Az Önemli lines under the dashboard table."""

    def test_all_three_severities_are_always_returned_in_order(self):
        self.assertEqual(
            [item["severity"] for item in summarize_severities([])],
            list(ISG_SEVERITIES),
        )

        for item in summarize_severities([]):
            with self.subTest(severity=item["severity"]):
                self.assertEqual(item["open"], 0)
                self.assertEqual(item["closed"], 0)
                self.assertEqual(item["total"], 0)

    def test_counts_are_split_by_status_and_severity(self):
        rows = [
            (ISG_SEVERITY_CRITICAL, ISG_STATUS_OPEN, 3),
            (ISG_SEVERITY_LOW, ISG_STATUS_OPEN, 2),
            (ISG_SEVERITY_LOW, ISG_STATUS_CLOSED, 1),
        ]

        by_code = {
            item["severity"]: item for item in summarize_severities(rows)
        }

        self.assertEqual(by_code[ISG_SEVERITY_CRITICAL]["open"], 3)
        self.assertEqual(by_code[ISG_SEVERITY_CRITICAL]["closed"], 0)
        self.assertEqual(by_code[ISG_SEVERITY_CRITICAL]["total"], 3)
        self.assertEqual(by_code[ISG_SEVERITY_LOW]["open"], 2)
        self.assertEqual(by_code[ISG_SEVERITY_LOW]["closed"], 1)
        self.assertEqual(by_code[ISG_SEVERITY_LOW]["total"], 3)
        # Nothing recorded with the default severity.
        self.assertEqual(by_code[ISG_SEVERITY_DEFAULT]["total"], 0)

    def test_labels_come_from_the_model(self):
        labels = {
            item["severity"]: item["severity_label"]
            for item in summarize_severities([])
        }

        self.assertEqual(labels, ISG_SEVERITY_LABELS)

    def test_unknown_severity_code_is_ignored(self):
        severities = summarize_severities(
            [("bilinmeyen", ISG_STATUS_OPEN, 5)]
        )

        self.assertEqual(sum(item["total"] for item in severities), 0)

    def test_string_counts_are_cast_to_int(self):
        item = summarize_severities(
            [(ISG_SEVERITY_CRITICAL, ISG_STATUS_OPEN, "4")]
        )[0]

        self.assertEqual(item["open"], 4)
        self.assertEqual(item["total"], 4)
        self.assertIsInstance(item["total"], int)

    def test_severity_item_matches_the_schema(self):
        item = summarize_severities(
            [(ISG_SEVERITY_CRITICAL, ISG_STATUS_CLOSED, 2)]
        )[0]

        parsed = IsgProjectSeverityItemSchema(**item)

        self.assertEqual(parsed.severity, ISG_SEVERITY_CRITICAL)
        self.assertEqual(parsed.severity_label, "Kritik")
        self.assertEqual(parsed.open, 0)
        self.assertEqual(parsed.closed, 2)

    def test_summary_with_severities_matches_the_project_summary_schema(self):
        summary = summarize_projects([(1, "SRU", ISG_STATUS_OPEN, 3)])
        summary["severities"] = summarize_severities(
            [
                (ISG_SEVERITY_LOW, ISG_STATUS_OPEN, 2),
                (ISG_SEVERITY_LOW, ISG_STATUS_CLOSED, 1),
            ]
        )

        parsed = IsgProjectSummarySchema(**summary)

        self.assertEqual(len(parsed.severities), 3)
        low = parsed.severities[2]
        self.assertEqual(low.severity, ISG_SEVERITY_LOW)
        self.assertEqual(low.severity_label, "Az Önemli")
        self.assertEqual(low.open, 2)
        self.assertEqual(low.closed, 1)
        self.assertEqual(low.total, 3)


class IsgRepositoryFilterTests(unittest.TestCase):
    def setUp(self):
        self.repository = IsgRepository(db=None)

    def test_search_matches_description_responsible_and_site_name(self):
        filters = self.repository._filters(search="  baret ")

        sql = compile_sql(filters[0])

        self.assertIn("description ILIKE", sql)
        self.assertIn("responsible_name ILIKE", sql)
        self.assertIn("territories.name ILIKE", sql)
        self.assertIn("%baret%", sql)

    def test_empty_search_adds_no_filter(self):
        self.assertEqual(self.repository._filters(search="   "), [])

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.repository._filters(status="beklemede")

        self.assertEqual(raised.exception.status_code, 400)

    def test_status_filter_uses_the_stored_code(self):
        sql = compile_sql(
            self.repository._filters(status=ISG_STATUS_CLOSED)[0]
        )

        self.assertIn("isg_nonconformities.status = 'kapali'", sql)

    def test_unknown_severity_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.repository._filters(severity="orta")

        self.assertEqual(raised.exception.status_code, 400)

    def test_severity_filter_uses_the_stored_code(self):
        sql = compile_sql(
            self.repository._filters(severity=ISG_SEVERITY_CRITICAL)[0]
        )

        self.assertIn("isg_nonconformities.severity = 'kritik'", sql)

    def test_territory_filter(self):
        sql = compile_sql(self.repository._filters(territory_id=3)[0])

        self.assertIn("territory_id = 3", sql)

    def test_responsible_filter_is_case_insensitive(self):
        sql = compile_sql(
            self.repository._filters(responsible_name="  ramiz khayramov ")[0]
        )

        self.assertIn("lower(isg_nonconformities.responsible_name)", sql)
        self.assertIn("'ramiz khayramov'", sql)

    def test_date_range_is_inclusive(self):
        filters = self.repository._filters(
            date_from=date(2026, 11, 1),
            date_to=date(2026, 11, 30),
        )

        sql = [compile_sql(condition) for condition in filters]

        self.assertIn("record_date >= '2026-11-01'", sql[0])
        self.assertIn("record_date <= '2026-11-30'", sql[1])

    def test_all_filters_are_combined(self):
        filters = self.repository._filters(
            search="baret",
            status=ISG_STATUS_OPEN,
            severity=ISG_SEVERITY_CRITICAL,
            territory_id=3,
            responsible_name="Mustafa Palta",
            date_from=date(2026, 11, 1),
            date_to=date(2026, 11, 30),
        )

        self.assertEqual(len(filters), 7)

    def test_pagination_limits(self):
        self.assertEqual(DEFAULT_LIMIT, 50)
        self.assertEqual(MAX_LIMIT, 100)

    def test_joined_names(self):
        self.assertEqual(joined_names("Ayşe", "Yılmaz"), "Ayşe Yılmaz")
        self.assertEqual(joined_names("Ayşe", None), "Ayşe")
        self.assertIsNone(joined_names(None, None))


class IsgMappingTests(unittest.TestCase):
    def test_row_mapping_includes_the_severity_label(self):
        record = SimpleNamespace(
            id=7,
            record_date=date(2026, 11, 22),
            description="Baret takılmıyor",
            status=ISG_STATUS_OPEN,
            severity=ISG_SEVERITY_CRITICAL,
            territory_id=3,
            responsible_name="Ramiz Khayramov",
            closed_at=None,
            closed_by_id=None,
            created_by_id=None,
            created_at=None,
            updated_at=None,
        )
        row = namedtuple(
            "Row",
            (
                "record",
                "territory_name",
                "creator_firstname",
                "creator_lastname",
                "closer_firstname",
                "closer_lastname",
            ),
        )(record, "SRU", None, None, None, None)

        item = IsgRepository(db=None)._row_to_item(row, [])

        self.assertEqual(item["severity"], ISG_SEVERITY_CRITICAL)
        self.assertEqual(item["severity_label"], "Kritik")
        self.assertEqual(item["status_label"], "Açık")


class IsgModelTests(unittest.TestCase):
    def test_table_names(self):
        self.assertEqual(IsgNonconformityModel.__tablename__, "isg_nonconformities")
        self.assertEqual(IsgAttachmentModel.__tablename__, "isg_attachments")

    def test_status_check_constraint_exists(self):
        names = {
            constraint.name
            for constraint in IsgNonconformityModel.__table__.constraints
        }

        self.assertIn("ck_isg_nonconformities_status", names)
        self.assertIn("ck_isg_nonconformities_severity", names)

    def test_status_column_default(self):
        column = IsgNonconformityModel.__table__.c.status

        self.assertFalse(column.nullable)
        self.assertEqual(column.server_default.arg, ISG_STATUS_OPEN)

    def test_severity_column_default(self):
        column = IsgNonconformityModel.__table__.c.severity

        self.assertFalse(column.nullable)
        self.assertEqual(column.server_default.arg, ISG_SEVERITY_DEFAULT)
        self.assertTrue(column.index)

    def test_description_column_is_text(self):
        self.assertIsInstance(
            IsgNonconformityModel.__table__.c.description.type, Text
        )

    def test_territory_delete_is_restricted(self):
        fk = next(
            constraint
            for constraint in IsgNonconformityModel.__table__.foreign_keys
            if constraint.parent.name == "territory_id"
        )

        self.assertEqual(fk.ondelete, "RESTRICT")

    def test_evidence_size_constraints(self):
        names = {
            constraint.name
            for constraint in IsgAttachmentModel.__table__.constraints
        }

        self.assertIn("ck_isg_attachments_size_positive", names)
        self.assertIn("ck_isg_attachments_size_limit", names)

    def test_evidence_follows_its_record(self):
        fk = next(
            constraint
            for constraint in IsgAttachmentModel.__table__.foreign_keys
            if constraint.parent.name == "nonconformity_id"
        )

        self.assertEqual(fk.ondelete, "CASCADE")

    def test_file_data_is_binary(self):
        self.assertIsInstance(
            IsgAttachmentModel.__table__.c.file_data.type, LargeBinary
        )


class IsgRouterTests(unittest.TestCase):
    def test_routes_are_registered(self):
        routes = {
            (route.path, tuple(sorted(route.methods)))
            for route in isg_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/fetch_nonconformities", ("GET",)), routes)
        self.assertIn(("/overview", ("GET",)), routes)
        self.assertIn(("/project_summary", ("GET",)), routes)
        self.assertIn(("/responsibles", ("GET",)), routes)
        self.assertIn(("/create", ("POST",)), routes)
        self.assertIn(("/update/{item_id}", ("PUT",)), routes)
        self.assertIn(("/{item_id}/status", ("PATCH",)), routes)
        self.assertIn(("/delete/{item_id}", ("DELETE",)), routes)
        self.assertIn(("/{item_id}/attachments", ("POST",)), routes)
        self.assertIn(
            ("/{item_id}/attachments/{attachment_id}", ("GET",)),
            routes,
        )
        self.assertIn(
            ("/{item_id}/attachments/{attachment_id}", ("DELETE",)),
            routes,
        )

    def test_created_and_deleted_status_codes(self):
        statuses = {
            (route.path, route.status_code)
            for route in isg_router.router.routes
            if hasattr(route, "methods")
        }

        self.assertIn(("/create", 201), statuses)
        self.assertIn(("/{item_id}/attachments", 201), statuses)
        self.assertIn(("/delete/{item_id}", 204), statuses)

    def test_responsibles_endpoint_returns_the_fixed_list(self):
        result = asyncio.run(isg_router.fetch_isg_responsibles())

        self.assertEqual(result["items"], list(ISG_RESPONSIBLES))


if __name__ == "__main__":
    unittest.main()
