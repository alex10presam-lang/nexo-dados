"""Validate and analyze a CSV in a temporary, request-local database."""
import csv
from datetime import date
from io import StringIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from investigator import Investigation, query, write_sales

COLUMNS = ("order_id", "order_date", "category", "region", "quantity", "unit_price_cents")
MAX_BYTES = 256 * 1024


def read_sales(content):
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Selecione um CSV UTF-8 de até 256 KiB.")
    content = content.removeprefix("\ufeff")
    delimiter = ";" if ";" in content.partition("\n")[0] else ","
    reader = csv.reader(StringIO(content, newline=""), delimiter=delimiter, strict=True)
    rows = []
    order_dates = {}
    try:
        if tuple(next(reader, ())) != COLUMNS:
            raise ValueError("Linha 1 · cabeçalho esperado: " + delimiter.join(COLUMNS))
        for values in reader:
            if not values:
                continue
            line = reader.line_num
            if len(values) != len(COLUMNS):
                raise ValueError(f"Linha {line} · esperado um valor por coluna.")
            order, day, category, region, quantity, price = (value.strip() for value in values)
            for column, value in zip(COLUMNS, (order, day, category, region, quantity, price)):
                if not value or len(value) > 120 or any(ord(char) < 32 for char in value):
                    raise ValueError(f"Linha {line} · {column}: informe um valor válido de até 120 caracteres.")
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError
            except ValueError:
                raise ValueError(f"Linha {line} · order_date: use uma data válida no formato AAAA-MM-DD.") from None
            if order_dates.setdefault(order, day) != day:
                raise ValueError(f"Linha {line} · order_date: use a mesma data em todos os itens do pedido.")
            if not re.fullmatch(r"[0-9]{1,6}", quantity) or int(quantity) == 0:
                raise ValueError(f"Linha {line} · quantity: use um inteiro entre 1 e 999999.")
            if not re.fullmatch(r"[0-9]{1,9}", price):
                raise ValueError(f"Linha {line} · unit_price_cents: use um inteiro de até 9 dígitos em centavos.")
            rows.append((order, day, category, region, int(quantity), int(price)))
    except csv.Error as error:
        raise ValueError(f"Linha {reader.line_num} · estrutura de CSV inválida.") from error
    if not rows:
        raise ValueError("O arquivo precisa conter pelo menos um item de venda.")
    return rows


def compare_sales(rows, previous, current):
    months = {row[1][:7] for row in rows}
    if not isinstance(previous, str) or not isinstance(current, str) or previous not in months or current not in months:
        raise ValueError("Selecione dois meses disponíveis no arquivo.")
    with TemporaryDirectory() as folder:
        database = Path(folder) / "import.sqlite"
        write_sales(database, rows)
        evidence = tuple(query(database, tool, previous, current) for tool in ("compare", "category", "region"))
    return Investigation(f"Comparação de {previous} com {current} calculada a partir do seu CSV.", evidence)
