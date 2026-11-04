import unittest

from portfolio import QUALITY_CSV, QUALITY_PLANS, dashboard, quality_investigation
from tabular import import_table, transform


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.columns, rows, _, _ = import_table({"format": "csv", "content": QUALITY_CSV})
        self.rows, self.preview = transform(self.columns, rows, {"operation": "duplicates"})

    def test_filtered_rate_preserves_audit_totals(self):
        self.assertEqual(self.preview["affected"], 1)
        response = dashboard(self.columns, self.rows, {
            "plans": [item["plan"] for item in QUALITY_PLANS],
            "dashboard_column": "Linha", "dashboard_value": "A", "dashboard_month": "2025-09",
        })
        rate = response["indicators"][0]["results"][0]
        self.assertEqual((rate["value"], rate["numerator"], rate["denominator"], rate["used"]),
                         ("8", "8", "100", 1))

    def test_comparison_returns_change_in_percentage_points(self):
        response = quality_investigation(self.columns, self.rows, "2025-08", "2025-09")
        self.assertEqual([(row["line"], row["delta"]) for row in response["changes"]],
                         [("A", "5"), ("B", "-1")])
