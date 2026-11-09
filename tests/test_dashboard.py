import unittest
from datetime import datetime
from addons_einvoicing.dashboard import summarize


class DashboardTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(summarize([]), ([], []))

    def test_counts_dates_and_order(self):
        counts, trend = summarize([
            {"status": "Approved", "creation": datetime(2026, 11, 9, 23, 59)},
            {"status": "Rejected", "creation": "2026-11-08 00:00:00"},
            {"status": "Approved", "creation": "2026-11-09 01:00:00.123456"},
        ])
        self.assertEqual(counts, [{"status": "Approved", "total": 2}, {"status": "Rejected", "total": 1}])
        self.assertEqual(trend, [{"day": "2026-11-08", "total": 1}, {"day": "2026-11-09", "total": 2}])

    def test_large_result_not_default_page_limited(self):
        rows = [{"status": "Queued", "creation": "2026-11-09"}] * 501
        self.assertEqual(summarize(rows)[0], [{"status": "Queued", "total": 501}])
