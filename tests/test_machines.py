"""Offline regression tests for the machine catalogue rules.

Run from ``server/``:
    python -m unittest discover -s tests -t . -v

These tests do not touch PostgreSQL. Scrapped ("Hurda") machines must stay in
the database -- history, spare part requests and audit trails still point at
them -- while disappearing from every list, machine picker and dashboard
counter. The helpers are covered in ``test_repair.py``; here we make sure every
query that feeds the UI actually calls them.
"""

import unittest
from inspect import getsource

from repositories.daily_fault_repository import DailyFaultRepository
from repositories.forum_repository import ForumRepository
from repositories.machines_repository import AllMachineRepository
from repositories.maintenance_repository import MaintenanceRepository
from repositories.purchase_request_repository import PurchaseRequestRepository
from repositories.repair_repository import RepairRepository
from repositories.tire_repository import TireRepository

SCRAP_CALL = "exclude_scrap_machines()"


class ScrapFilteredMachineListTests(unittest.TestCase):
    """The machine table and its dashboard counters skip scrapped machines."""

    def test_machine_list_excludes_scrap_machines(self):
        source = getsource(AllMachineRepository.fetch_paginated)
        self.assertIn(SCRAP_CALL, source)

    def test_status_statistics_excludes_scrap_machines(self):
        source = getsource(AllMachineRepository.get_status_statistics)

        # The total count ignores scrapped machines ...
        self.assertIn(SCRAP_CALL, source)
        # ... and the "Hurda" card itself is dropped from the KPI row.
        self.assertIn("is_scrap_status_name(", source)

    def test_pivot_statistics_excludes_scrap_machines(self):
        source = getsource(AllMachineRepository.get_type_territory_pivot)
        self.assertIn(SCRAP_CALL, source)


class ScrapFilteredModuleListTests(unittest.TestCase):
    """Every module that lists machines filters scrapped ones out."""

    def test_module_lists_exclude_scrap_machines(self):
        lists = {
            "repair": RepairRepository._fetch_items,
            "maintenance": MaintenanceRepository._fetch_items,
            "tire": TireRepository._fetch_items,
            "daily_fault": DailyFaultRepository._fetch_items,
        }

        for label, method in lists.items():
            with self.subTest(module=label):
                self.assertIn(SCRAP_CALL, getsource(method))

    def test_repair_summary_counts_exclude_scrap_machines(self):
        source = getsource(RepairRepository.get_summary)
        self.assertIn(SCRAP_CALL, source)


class ScrapFilteredPickerTests(unittest.TestCase):
    """Machine type-ahead pickers never offer scrapped equipment."""

    def test_machine_pickers_exclude_scrap_machines(self):
        pickers = {
            "repair": RepairRepository.get_machine_options,
            "tire": TireRepository.get_machine_options,
            "daily_fault": DailyFaultRepository.get_machine_options,
            "purchase_request": PurchaseRequestRepository.get_machine_options,
            "forum": ForumRepository.search_machine_options,
        }

        for label, method in pickers.items():
            with self.subTest(module=label):
                self.assertIn(SCRAP_CALL, getsource(method))


if __name__ == "__main__":
    unittest.main()
