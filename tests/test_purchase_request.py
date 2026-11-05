"""Offline regression tests for purchase requests (spare part + service).

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. They cover the write schemas (trimming,
required fields, quantity/unit rules, status literals) and the pure repository
helpers used by the list endpoint.
"""

import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from models.purchase_request_model import status_label
from repositories.purchase_request_repository import (
    MAX_LIMIT,
    build_search_pattern,
    clamp_pagination,
    machine_label,
    validate_status_filter,
)
from schemas.purchase_request_schemas import (
    ServiceRequestCreateSchema,
    SparePartRequestCreateSchema,
    SparePartStatusUpdateSchema,
)


def item(**overrides):
    data = {
        "machine_id": 12,
        "garage_request_no": " G-101 ",
        "part_number": " 6CT-001 ",
        "description_ru": "  Фильтр масляный ",
        "description_tr": "",
        "quantity": "2",
        "unit": " Ad ",
        "supply_date": "2026-11-15",
    }
    data.update(overrides)
    return data


def payload(**overrides):
    data = {
        "title": "  Şanzıman yedek parça talebi ",
        "stf_htf_no": " STF-2026-14 ",
        "territory_id": 3,
        "request_type_id": 1,
        "request_date": "2026-10-31",
        "items": [item()],
    }
    data.update(overrides)
    return data


class SparePartRequestCreateSchemaTests(unittest.TestCase):
    def test_normalizes_header_and_rows(self):
        parsed = SparePartRequestCreateSchema(**payload())

        self.assertEqual(parsed.title, "Şanzıman yedek parça talebi")
        self.assertEqual(parsed.stf_htf_no, "STF-2026-14")
        self.assertEqual(parsed.status, "bekleniyor")
        self.assertEqual(parsed.request_date, date(2026, 10, 31))

        row = parsed.items[0]
        self.assertEqual(row.garage_request_no, "G-101")
        self.assertEqual(row.part_number, "6CT-001")
        self.assertEqual(row.description_ru, "Фильтр масляный")
        self.assertIsNone(row.description_tr)  # blank text -> null
        self.assertEqual(row.unit, "Ad")
        self.assertEqual(row.quantity, Decimal("2"))
        self.assertEqual(row.supply_date, date(2026, 11, 15))

    def test_one_request_may_cover_several_machines(self):
        parsed = SparePartRequestCreateSchema(
            **payload(
                items=[
                    item(machine_id=12),
                    item(machine_id=13, garage_request_no=None),
                    item(machine_id=12, part_number="6CT-002"),
                ]
            )
        )
        self.assertEqual(len(parsed.items), 3)
        self.assertIsNone(parsed.items[1].garage_request_no)

    def test_items_are_required(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(items=[]))

    def test_blank_header_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(title="   "))
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(stf_htf_no=""))

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(items=[item(quantity="0")]))

    def test_unit_is_required(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(items=[item(unit="  ")]))

    def test_status_accepts_only_two_values(self):
        self.assertEqual(
            SparePartRequestCreateSchema(**payload(status="geldi")).status,
            "geldi",
        )
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(status="tamirde"))

    def test_ids_must_be_positive(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(territory_id=0))
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(request_type_id=0))
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(items=[item(machine_id=0)]))

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(machine_id=5))
        with self.assertRaises(ValidationError):
            SparePartRequestCreateSchema(**payload(items=[item(supplier="ACME")]))


class StatusSchemaTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(
            SparePartStatusUpdateSchema(status=" GELDI ").status, "geldi"
        )

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValidationError):
            SparePartStatusUpdateSchema(status="iptal")


class ServiceRequestCreateSchemaTests(unittest.TestCase):
    def service_payload(self, **overrides):
        data = {
            "title": "  Vinç bakım hizmeti ",
            "service_form_no": " SRV-77 ",
            "machine_id": 4,
            "company_name": "  ACME Servis ",
            "service_description": "  Hidrolik kaçak onarımı ",
            "request_date": "2026-10-30",
        }
        data.update(overrides)
        return data

    def test_normalizes_values(self):
        parsed = ServiceRequestCreateSchema(**self.service_payload())
        self.assertEqual(parsed.title, "Vinç bakım hizmeti")
        self.assertEqual(parsed.service_form_no, "SRV-77")
        self.assertEqual(parsed.company_name, "ACME Servis")
        self.assertEqual(parsed.service_description, "Hidrolik kaçak onarımı")
        self.assertEqual(parsed.request_date, date(2026, 10, 30))

    def test_required_fields(self):
        for field in (
            "title",
            "service_form_no",
            "company_name",
            "service_description",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    ServiceRequestCreateSchema(
                        **self.service_payload(**{field: "   "})
                    )

    def test_description_length_is_limited(self):
        with self.assertRaises(ValidationError):
            ServiceRequestCreateSchema(
                **self.service_payload(service_description="x" * 4001)
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ServiceRequestCreateSchema(
                **self.service_payload(company_phone="555")
            )


class RepositoryHelperTests(unittest.TestCase):
    def test_clamp_pagination_uses_defaults_and_limits(self):
        self.assertEqual(clamp_pagination(0, -5), (20, 0))
        self.assertEqual(clamp_pagination(500, 10), (MAX_LIMIT, 10))
        self.assertEqual(clamp_pagination(15, 30), (15, 30))

    def test_build_search_pattern(self):
        self.assertIsNone(build_search_pattern(None))
        self.assertIsNone(build_search_pattern("   "))
        self.assertEqual(build_search_pattern(" stf-1 "), "%stf-1%")

    def test_machine_label_prefers_identification_no(self):
        self.assertEqual(machine_label("ID-100", "34ABC", "VIN1", 7), "ID-100")
        self.assertEqual(machine_label(None, "34ABC", "VIN1", 7), "34ABC")
        self.assertEqual(machine_label("  ", None, "VIN1", 7), "VIN1")
        self.assertEqual(machine_label(None, None, None, 7), "Makine #7")

    def test_validate_status_filter(self):
        self.assertIsNone(validate_status_filter(None))
        self.assertIsNone(validate_status_filter("  "))
        self.assertEqual(validate_status_filter(" GELDI "), "geldi")
        with self.assertRaises(HTTPException) as ctx:
            validate_status_filter("tamirde")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_status_label_is_turkish_and_falls_back(self):
        self.assertEqual(status_label("geldi"), "Geldi")
        self.assertEqual(status_label("bekleniyor"), "Bekleniyor")
        self.assertEqual(status_label(None), "Bekleniyor")


class ColumnFilterParamTests(unittest.TestCase):
    """The Excel-style column filters must reach the repository."""

    def test_repository_accepts_service_column_filters(self):
        from inspect import signature

        from repositories.purchase_request_repository import (
            PurchaseRequestRepository,
        )

        column_filters = (
            "identification_no",
            "company_name",
            "service_description",
            "date_from",
            "date_to",
        )

        for method_name in ("_service_rows", "fetch_service_requests"):
            params = signature(
                getattr(PurchaseRequestRepository, method_name)
            ).parameters
            for filter_name in column_filters:
                with self.subTest(method=method_name, filter=filter_name):
                    self.assertIn(filter_name, params)
                    self.assertIsNone(params[filter_name].default)

    def test_repository_accepts_spare_part_machine_filter(self):
        from inspect import signature

        from repositories.purchase_request_repository import (
            PurchaseRequestRepository,
        )

        for method_name in ("_spare_rows", "fetch_spare_part_requests"):
            params = signature(
                getattr(PurchaseRequestRepository, method_name)
            ).parameters
            with self.subTest(method=method_name):
                self.assertIn("identification_no", params)
                self.assertIsNone(params["identification_no"].default)

    def test_list_endpoints_expose_column_filters(self):
        from inspect import signature

        from routers.purchase_request_router import (
            fetch_service_requests,
            fetch_spare_part_requests,
        )

        cases = (
            (fetch_spare_part_requests, ("identification_no",)),
            (
                fetch_service_requests,
                ("identification_no", "company_name", "service_description"),
            ),
        )

        for endpoint, filter_names in cases:
            params = signature(endpoint).parameters
            for filter_name in filter_names:
                with self.subTest(endpoint=endpoint.__name__, filter=filter_name):
                    self.assertIn(filter_name, params)
                    # FastAPI wraps the default in Query(...)
                    default = params[filter_name].default
                    self.assertIsNone(getattr(default, "default", default))


if __name__ == "__main__":
    unittest.main()
