"""Run a small, reproducible live evaluation and print evidence as JSON."""
import json
import os

from model import OpenAIModel
from portfolio import QUALITY_CSV
from tabular import aggregate, choose_plan, import_table, profile, transform

CASES = [
    ("Qual linha teve a maior taxa de rejeição? Use rejeitados sobre inspecionados.",
     {"operation": "ratio", "column": "Rejeitados", "denominator": "Inspecionados", "group": "Linha"},
     "A"),
    ("Some a coluna Inspecionados em toda a tabela.", {"operation": "sum", "column": "Inspecionados"}, None),
    ("Qual foi o custo em reais dos defeitos?", None, None),
    ("Qual é a taxa?", None, None),
    ("Calcule a taxa de rejeição da linha Z. Filtre Linha por Z e use Rejeitados sobre Inspecionados.",
     {"operation": "ratio", "column": "Rejeitados", "denominator": "Inspecionados",
      "filter_column": "Linha", "filter_value": "Z"}, None),
]


def evaluate(provider):
    columns, rows, _, _ = import_table({"format": "csv", "content": QUALITY_CSV + "2025-09-04,Z,0,0\n"})
    rows, _ = transform(columns, rows, {"operation": "duplicates"})
    report = []
    for question, expected, leader in CASES:
        record = {"question": question, "expected_plan": expected, "expected_leader": leader}
        try:
            plan = choose_plan(provider, question, profile(columns, rows))
            if isinstance(plan, str):
                record.update(clarification=plan, passed=expected is None)
            else:
                results = aggregate(columns, rows, plan)["results"]
                correct = expected is not None and all(plan.get(key) == value for key, value in expected.items())
                if expected and not expected.get("filter_column"):
                    correct = correct and not plan.get("filter_column")
                if expected and expected.get("filter_value") == "Z":
                    correct = correct and bool(results) and results[0]["value"] is None
                if expected and not expected.get("group"):
                    correct = correct and not plan.get("group")
                if leader:
                    correct = correct and bool(results) and results[0]["group"] == leader
                record.update(plan=plan, results=results, passed=bool(correct))
        except ValueError as error:
            record.update(error=str(error), passed=False)
        report.append(record)
    return report


if __name__ == "__main__":
    key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if not key or not model:
        raise SystemExit("Configure OPENAI_API_KEY e OPENAI_MODEL para avaliar a API ao vivo.")
    report = evaluate(OpenAIModel(key, model))
    print(json.dumps({"model": model, "cases": report}, ensure_ascii=True, indent=2))
    raise SystemExit(0 if all(case["passed"] for case in report) else 1)
