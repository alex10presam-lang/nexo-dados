"""Reproducible industrial-quality case and dashboard calculations."""
from decimal import Decimal

from tabular import LIMIT, aggregate, import_table, parse_date

QUALITY_COLUMNS = ("Data", "Linha", "Rejeitados", "Inspecionados")
QUALITY_CSV = """Data,Linha,Rejeitados,Inspecionados
2025-07-02,A,2,100
2025-07-03,B,4,100
2025-08-02,A,3,100
2025-08-03,B,4,100
2025-09-02,A,8,100
2025-09-02,A,8,100
2025-09-03,B,3,100
"""
RATE = {"operation": "ratio", "column": "Rejeitados", "denominator": "Inspecionados"}
QUALITY_PLANS = [
    {"title": "Taxa de rejeição", "plan": RATE},
    {"title": "Volume inspecionado", "plan": {"operation": "sum", "column": "Inspecionados"}},
    {"title": "Evolução mensal da rejeição", "plan": {**RATE, "group": "Data", "monthly": True}},
    {"title": "Ranking por linha", "plan": {**RATE, "group": "Linha"}},
]


def filter_rows(columns, rows, data):
    column, value = data.get("dashboard_column"), data.get("dashboard_value")
    if column:
        if column not in columns or not isinstance(value, str):
            raise ValueError("Escolha um filtro válido.")
        index = columns.index(column)
        rows = [row for row in rows if row[index] == value]
    month = data.get("dashboard_month")
    if month:
        if "Data" not in columns or not isinstance(month, str):
            raise ValueError("Escolha um mês válido.")
        index = columns.index("Data")
        rows = [row for row in rows if (parse_date(row[index]) or "")[:7] == month]
    return rows


def dashboard(columns, rows, data):
    plans = data.get("plans")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 8:
        raise ValueError("Fixe entre 1 e 8 indicadores.")
    rows = filter_rows(columns, rows, data)
    return {"indicators": [aggregate(columns, rows, plan) for plan in plans], "filtered_rows": len(rows)}


def combine_tables(columns, rows, data):
    second = data.get("second")
    if not isinstance(second, dict):
        raise ValueError("Selecione o segundo arquivo.")
    other_columns, other_rows, _, _ = import_table(second)
    mapping = data.get("mapping", {})
    if not isinstance(mapping, dict) or any(key not in columns or value not in other_columns
                                            for key, value in mapping.items()):
        raise ValueError("Confira a correspondência das colunas.")
    aligned = {column: mapping.get(column, column) for column in columns}
    sources = [source for source in aligned.values() if source in other_columns]
    if len(sources) != len(set(sources)):
        raise ValueError("Use cada coluna do segundo arquivo uma única vez.")
    missing = [column for column, source in aligned.items() if source not in other_columns]
    if missing:
        raise ValueError("Mapeie as colunas ausentes: " + ", ".join(missing))
    positions = [other_columns.index(aligned[column]) for column in columns]
    origin = "Arquivo de origem"
    while origin in columns:
        origin += " ·"
    first_name = str(data.get("name") or "Primeiro arquivo")[:160]
    second_name = str(second.get("name") or "Segundo arquivo")[:160]
    if first_name == second_name:
        first_name += " (1)"
        second_name += " (2)"
    combined = [row + [first_name] for row in rows]
    combined.extend([row[index] for index in positions] + [second_name] for row in other_rows)
    if len(combined) > 10000 or len(columns) >= 100:
        raise ValueError("A combinação deve ter até 10.000 linhas e 100 colunas, incluindo a origem.")
    return [*columns, origin], combined


def quality_investigation(columns, rows, previous, current):
    if not all(column in columns for column in QUALITY_COLUMNS):
        raise ValueError("A investigação de qualidade usa Data, Linha, Rejeitados e Inspecionados.")
    if not isinstance(previous, str) or not isinstance(current, str) or previous >= current:
        raise ValueError("Selecione dois meses em ordem cronológica.")
    date_index = columns.index("Data")
    periods = {}
    for month in (previous, current):
        subset = [row for row in rows if (parse_date(row[date_index]) or "")[:7] == month]
        if not subset:
            raise ValueError(f"Sem registros em {month}.")
        periods[month] = {
            "total": aggregate(columns, subset, RATE)["results"][0],
            "lines": aggregate(columns, subset, {**RATE, "group": "Linha"})["results"],
        }
    before, after = (periods[month] for month in (previous, current))
    old = {row["group"]: row for row in before["lines"]}
    changes = []
    for row in after["lines"]:
        base = old.get(row["group"])
        if base and base["value"] is not None and row["value"] is not None:
            delta = Decimal(row["value"]) - Decimal(base["value"])
            changes.append({"line": row["group"], "previous": base, "current": row, "delta": str(delta)})
    changes.sort(key=lambda row: Decimal(row["delta"]), reverse=True)
    return {"periods": periods, "changes": changes, "plan": RATE}
