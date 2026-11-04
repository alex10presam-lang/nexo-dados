from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investigator import seed, query, investigate, Call


class InvestigationTests(unittest.TestCase):
    def test_agent_requests_period_without_querying_database(self):
        from investigator import Clarification

        def model(question, history):
            self.assertEqual(question, "Por que as vendas caíram?")
            self.assertEqual(history, ())
            return Clarification("Quais meses você quer comparar?")

        result = investigate("Por que as vendas caíram?", self.db.with_suffix(".missing"), model)
        self.assertEqual(result.answer, "Quais meses você quer comparar?")
        self.assertEqual(result.evidence, ())
        self.assertTrue(result.needs_clarification)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "sales.sqlite"
        seed(self.db)

    def test_september_and_category_contributions(self):
        report = query(self.db, "compare", "2025-08", "2025-09")
        self.assertEqual(report.rows[0]["receita_centavos"], 100_000)
        self.assertEqual(report.rows[1]["receita_centavos"], 80_000)
        self.assertEqual(report.rows[0]["pedidos"], 10)
        details = query(self.db, "category", "2025-08", "2025-09")
        by_group = {row["grupo"]: row["variacao_centavos"] for row in details.rows}
        self.assertEqual(by_group["Eletrônicos"], -15_000)
        self.assertEqual(by_group["Papelaria"], -5_000)
        self.assertEqual(sum(by_group.values()), -20_000)

    def test_october_and_missing_november(self):
        report = query(self.db, "compare", "2025-09", "2025-10")
        self.assertEqual([row["pedidos"] for row in report.rows], [8, 10])
        self.assertEqual([row["ticket_centavos"] for row in report.rows], [10_000, 10_000])
        missing = query(self.db, "region", "2025-10", "2025-11")
        self.assertEqual(missing.missing, ("2025-11",))
        self.assertFalse(missing.rows)

    def test_invalid_tool_and_month(self):
        for tool, month in [("DROP TABLE sales", "2025-08"), ("compare", "2025-13")]:
            with self.assertRaises(ValueError):
                query(self.db, tool, month, "2025-09")

    def test_agent_selects_multiple_tools_and_receives_results(self):
        def model(question, history):
            self.assertEqual(question, "Por que setembro caiu?")
            if not history:
                return Call("compare", "2025-08", "2025-09")
            if len(history) == 1:
                return Call("category", "2025-08", "2025-09")
            self.assertEqual(history[-1].rows[0]["variacao_centavos"], -15_000)
            return "Eletrônicos respondeu por R$ 150 da queda."

        result = investigate("Por que setembro caiu?", self.db, model)
        self.assertIn("R$ 150", result.answer)
        self.assertEqual([item.tool for item in result.evidence], ["compare", "category"])

    def test_agent_stops_for_missing_month(self):
        def model(question, history):
            self.assertFalse(history)
            return Call("compare", "2025-10", "2025-11")

        self.assertIn("2025-11", investigate("Novembro?", self.db, model).answer)
