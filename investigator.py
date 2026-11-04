"""Deterministic sales data, read-only analytics and bounded investigation."""
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import sqlite3
from typing import Callable


def write_sales(db_path: Path, rows) -> None:
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS sales (
            order_id TEXT, order_date TEXT, category TEXT, region TEXT,
            quantity INTEGER, unit_price_cents INTEGER)""")
        connection.execute("DELETE FROM sales")
        connection.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)", rows)


def seed(db_path: Path) -> None:
    rows = []
    for month, electronics, stationery in [(8, 6, 4), (9, 4, 4), (10, 6, 4)]:
        categories = ["Eletrônicos"] * electronics + ["Papelaria"] * stationery
        for index, category in enumerate(categories, 1):
            order = f"2025-{month:02d}-{index:02d}"
            region = "Norte" if index % 2 else "Sudeste"
            price = 10_000
            if month == 9:
                price = 11_250 if category == "Eletrônicos" else 8_750
            rows.extend([(order, order, category, region, 1, price - 2_500),
                         (order, order, category, region, 1, 2_500)])
    write_sales(db_path, rows)


MONTHS_SQL = """SELECT substr(order_date, 1, 7) AS mes,
       SUM(quantity * unit_price_cents) AS receita_centavos,
       COUNT(DISTINCT order_id) AS pedidos,
       SUM(quantity * unit_price_cents) * 1.0 / COUNT(DISTINCT order_id) AS ticket_centavos
FROM sales WHERE substr(order_date, 1, 7) IN (:previous, :current)
GROUP BY mes ORDER BY mes"""

BREAKDOWN_SQL = """WITH totais AS (
  SELECT {dimension} AS grupo,
    SUM(CASE WHEN substr(order_date, 1, 7) = :previous
        THEN quantity * unit_price_cents ELSE 0 END) AS anterior_centavos,
    SUM(CASE WHEN substr(order_date, 1, 7) = :current
        THEN quantity * unit_price_cents ELSE 0 END) AS atual_centavos
  FROM sales WHERE substr(order_date, 1, 7) IN (:previous, :current)
  GROUP BY {dimension}
)
SELECT *, atual_centavos - anterior_centavos AS variacao_centavos
FROM totais ORDER BY abs(atual_centavos - anterior_centavos) DESC, grupo"""

TOOLS = {
    "compare": "Compara receita bruta, pedidos distintos e ticket médio entre dois meses.",
    "category": "Decompõe a variação da receita por categoria de produto.",
    "region": "Decompõe a variação da receita por região.",
}


@dataclass(frozen=True)
class Call:
    tool: str
    previous: str
    current: str


@dataclass(frozen=True)
class Evidence:
    tool: str
    params: dict
    sql: str
    rows: list[dict]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class Clarification:
    question: str


@dataclass(frozen=True)
class Investigation:
    answer: str
    evidence: tuple[Evidence, ...]
    needs_clarification: bool = False


def query(db_path: Path, tool: str, previous: str, current: str) -> Evidence:
    if tool not in TOOLS:
        raise ValueError("Ferramenta desconhecida.")
    for month in (previous, current):
        if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("Use meses no formato AAAA-MM.")
        date.fromisoformat(month + "-01")
    if previous >= current:
        raise ValueError("Escolha dois meses em ordem cronológica.")

    params = {"previous": previous, "current": current}
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        monthly = [dict(row) for row in db.execute(MONTHS_SQL, params)]
        present = {row["mes"] for row in monthly}
        missing = tuple(month for month in (previous, current) if month not in present)
        if missing:
            return Evidence(tool, params, MONTHS_SQL, [], missing)
        if tool == "compare":
            return Evidence(tool, params, MONTHS_SQL, monthly, ())
        sql = BREAKDOWN_SQL.format(dimension=tool)
        return Evidence(tool, params, sql, [dict(row) for row in db.execute(sql, params)], ())


def investigate(
    question: str, db_path: Path,
    model: Callable[[str, tuple[Evidence, ...]], Call | Clarification | str],
) -> Investigation:
    evidence = []
    for _ in range(6):
        decision = model(question, tuple(evidence))
        if isinstance(decision, Clarification):
            if not decision.question.strip():
                raise ValueError("A IA pediu esclarecimento sem indicar o que falta.")
            return Investigation(decision.question, tuple(evidence), True)
        if isinstance(decision, str):
            if not evidence or not decision.strip():
                raise ValueError("A IA não apresentou uma investigação com evidências.")
            return Investigation(decision, tuple(evidence))
        if len(evidence) == 5:
            break
        if evidence and evidence[0].params != {
            "previous": decision.previous, "current": decision.current
        }:
            raise ValueError("A IA tentou misturar períodos na mesma investigação.")
        report = query(db_path, decision.tool, decision.previous, decision.current)
        evidence.append(report)
        if report.missing:
            months = ", ".join(report.missing)
            return Investigation(f"Sem registros para {months}. Comparação indisponível.", tuple(evidence))
    raise ValueError("A investigação atingiu o limite de cinco consultas.")
