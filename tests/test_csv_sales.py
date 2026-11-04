import unittest

from csv_sales import read_sales


HEADER = "order_id,order_date,category,region,quantity,unit_price_cents\n"


class CsvSalesTests(unittest.TestCase):
    def test_preview_and_comparison(self):
        from csv_sales import compare_sales

        rows = read_sales(HEADER + "a,2025-08-01,Papelaria,Norte,2,300\n"
                          "b,2025-09-01,Papelaria,Norte,1,300\n")
        result = compare_sales(rows, "2025-08", "2025-09")
        self.assertEqual(result.evidence[0].rows[0]["receita_centavos"], 600)
        self.assertEqual(result.evidence[1].rows[0]["variacao_centavos"], -300)

    def test_reports_line_and_column(self):
        with self.assertRaisesRegex(ValueError, "Linha 2.*order_date"):
            read_sales(HEADER + "a,2025-02-30,Papelaria,Norte,2,300\n")
