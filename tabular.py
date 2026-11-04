"""Import one table and run a validated aggregation over it."""
import base64
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
import json
from statistics import median
from zipfile import BadZipFile, ZipFile

LIMIT = 1024 * 1024
OPERATIONS = ("count", "sum", "mean", "median", "min", "max", "missing", "ratio")


def import_table(data):
    header = data.get("header", 1)
    if type(header) is not int or not 1 <= header <= 100:
        raise ValueError("Informe uma linha de cabeçalho entre 1 e 100.")
    content = data.get("content")
    if not isinstance(content, str):
        raise ValueError("Selecione um arquivo CSV ou Excel.")
    if data.get("format") == "xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Instale a dependência Excel indicada no README.") from None
        try:
            raw = base64.b64decode(content, validate=True)
            if len(raw) > LIMIT:
                raise ValueError("Use um arquivo de até 1 MiB.")
            with ZipFile(BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 16 * LIMIT:
                    raise ValueError("A planilha descompactada excede 16 MiB.")
            book = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
            try:
                sheets = book.sheetnames
                if data.get("action") == "preview" and not data.get("sheet"):
                    return [], [], sheets, None
                sheet = data.get("sheet") or sheets[0]
                if sheet not in sheets:
                    raise ValueError("Selecione uma aba válida.")
                worksheet = book[sheet]
                if (worksheet.max_row or 0) > header + 10000 or (worksheet.max_column or 0) > 100:
                    raise ValueError("O limite é de 10.000 linhas de dados e 100 colunas.")
                worksheet.reset_dimensions()
                rows = []
                for index, row in enumerate(worksheet.values, 1):
                    if index > header + 10000 or len(row) > 100:
                        raise ValueError("O limite é de 10.000 linhas de dados e 100 colunas.")
                    rows.append(row)
                width = max(map(len, rows), default=0)
                rows = [row + (None,) * (width - len(row)) for row in rows]
            finally:
                book.close()
        except ValueError:
            raise
        except (BadZipFile, OSError, KeyError, TypeError, IndexError, SyntaxError) as error:
            raise ValueError("Não foi possível ler o arquivo Excel.") from error
    elif data.get("format") == "csv":
        if len(content.encode("utf-8")) > LIMIT:
            raise ValueError("Use um arquivo de até 1 MiB.")
        content = content.removeprefix("\ufeff")
        try:
            sample = content.splitlines()
            delimiter = csv.Sniffer().sniff(sample[header - 1] if len(sample) >= header else "",
                                             delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
        try:
            rows = list(csv.reader(StringIO(content, newline=""), delimiter=delimiter, strict=True))
        except csv.Error as error:
            raise ValueError("Estrutura de CSV inválida.") from error
        sheets, sheet = [], None
    else:
        raise ValueError("Selecione um arquivo CSV ou XLSX.")

    if len(rows) <= header:
        raise ValueError("Escolha uma linha de cabeçalho seguida de dados.")
    columns = [str(value).strip() if value is not None else "" for value in rows[header - 1]]
    while data.get("format") == "xlsx" and columns and not columns[-1]:
        columns.pop()
    rows = [(index, [str(value).strip() if value is not None else "" for value in row])
            for index, row in enumerate(rows[header:], header + 1) if any(value not in ("", None) for value in row)]
    if len(rows) > 10000 or len(columns) > 100:
        raise ValueError("O limite é de 10.000 linhas de dados e 100 colunas.")
    if any(not name or len(name) > 120 for name in columns) or len(set(columns)) != len(columns):
        raise ValueError("Use cabeçalhos únicos e preenchidos, com até 120 caracteres.")
    records = []
    for index, values in rows:
        if data.get("format") == "xlsx" and not any(values[len(columns):]):
            values = values[:len(columns)]
        if len(values) != len(columns):
            raise ValueError(f"Linha {index}: a quantidade de campos difere do cabeçalho.")
        records.append(values)
    if not records:
        raise ValueError("A tabela precisa de pelo menos uma linha de dados.")
    return columns, records, sheets, sheet


def number(value):
    try:
        parsed = Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and (not parsed or abs(parsed.adjusted()) <= 100) else None


def profile(columns, rows):
    result = []
    for name, values in zip(columns, zip(*rows)):
        filled = [value for value in values if value]
        result.append({"name": name, "type": "number" if filled and all(number(v) is not None for v in filled)
                       else "text", "missing": len(rows) - len(filled)})
    return result


def parse_date(value):
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def diagnosis(columns, rows):
    details = profile(columns, rows)
    for index, item in enumerate(details):
        values = {row[index] for row in rows if row[index]}
        item["numeric_values"] = sum(bool(row[index]) and number(row[index]) is not None for row in rows)
        dates = {value for value in values if parse_date(value)}
        item["date_values"] = sum(row[index] in dates for row in rows)
        item["date_formats"] = len({"/" if "/" in value else "datetime" if " " in value else "ISO"
                                    for value in dates})
        item["category_variants"] = len(values) - len({" ".join(v.split()).casefold() for v in values})
    return {"columns": details, "duplicates": len(rows) - len(set(map(tuple, rows)))}


def transform(columns, rows, rule):
    if not isinstance(rule, dict):
        raise ValueError("Escolha uma correção válida.")
    operation = rule.get("operation")
    examples = []
    if operation == "duplicates":
        seen = set()
        output = []
        for row in rows:
            key = tuple(row)
            if key in seen:
                if len(examples) < 5:
                    examples.append([" | ".join(row)[:160], "Linha removida"])
            else:
                seen.add(key)
                output.append(row)
        return output, {"affected": len(rows) - len(output), "examples": examples, "invalid": 0}
    name = rule.get("column")
    if name not in columns or operation not in ("number", "date", "category"):
        raise ValueError("Escolha a coluna e a correção.")
    index = columns.index(name)
    output = []
    affected = invalid = 0
    for row in rows:
        value = row[index]
        converted = value
        if value and operation == "number":
            parsed = number(value)
            converted = format(parsed, "f") if parsed is not None else None
        elif value and operation == "date":
            converted = parse_date(value)
        elif value and operation == "category":
            converted = " ".join(value.split()).casefold()
        if converted is None:
            invalid += 1
            converted = value
        if converted != value:
            affected += 1
            if len(examples) < 5:
                examples.append([value, converted])
        output.append(row[:index] + [converted] + row[index + 1:])
    return output, {"affected": affected, "examples": examples, "invalid": invalid}


def aggregate(columns, rows, plan):
    if not isinstance(plan, dict):
        raise ValueError("Operação inválida.")
    operation = plan.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("Operação desconhecida.")

    def index(key, required=False):
        name = plan.get(key)
        if name in ("", None) and not required:
            return None
        if name not in columns:
            raise ValueError(f"Coluna ausente ou inválida para {key}: {name or '(vazia)'}.")
        return columns.index(name)

    metric = index("column", operation != "count")
    group = index("group")
    monthly = plan.get("monthly") is True
    if monthly and group is None:
        raise ValueError("Escolha a coluna de data para o agrupamento mensal.")
    denominator = index("denominator", True) if operation == "ratio" else None
    filter_column = index("filter_column")
    filter_value = plan.get("filter_value", "")
    if filter_column is not None and not isinstance(filter_value, str):
        raise ValueError("O valor do filtro deve ser texto.")
    buckets = {} if group is not None else {None: []}
    for row in rows:
        if filter_column is None or row[filter_column] == filter_value:
            label = row[group] if group is not None else None
            if monthly and label:
                day = parse_date(label)
                if not day:
                    raise ValueError("Corrija as datas antes de agrupar por mês.")
                label = day[:7]
            buckets.setdefault(label, []).append(row)
    results = []
    for label, bucket in buckets.items():
        evidence = {}
        if operation == "count":
            value = len(bucket)
        elif operation == "missing":
            value = sum(not row[metric] for row in bucket)
        else:
            values = [number(row[metric]) for row in bucket if row[metric]]
            if None in values:
                raise ValueError("A coluna da métrica contém valores não numéricos.")
            if operation == "ratio":
                pairs = [(number(row[metric]), number(row[denominator])) for row in bucket
                         if row[metric] and row[denominator]]
                if any(None in pair for pair in pairs):
                    raise ValueError("O denominador contém valores não numéricos.")
                total = sum(pair[1] for pair in pairs)
                numerator = sum(pair[0] for pair in pairs)
                value = 100 * numerator / total if total else None
                evidence = {"numerator": str(numerator), "denominator": str(total), "used": len(pairs)}
            else:
                calculate = {"sum": sum, "mean": lambda values: sum(values) / len(values),
                             "median": median, "min": min, "max": max}
                value = calculate[operation](values) if values else None
            if operation != "ratio":
                evidence["used"] = len(values)
        results.append({"group": label, "value": str(value) if value is not None else None,
                        "rows": len(bucket), **evidence})
    if monthly:
        results.sort(key=lambda item: (not item["group"], item["group"]))
    else:
        results.sort(key=lambda item: (item["value"] is None, -Decimal(item["value"] or "0")))
    return {"results": results[:100], "total_groups": len(results), "plan": {
        key: plan.get(key) for key in ("operation", "column", "group", "denominator", "filter_column", "filter_value", "monthly")
    }}


def choose_plan(model, question, schema):
    fields = ("operation", "column", "group", "denominator", "filter_column", "filter_value")
    properties = {field: {"type": "string"} for field in fields}
    properties["operation"]["enum"] = list(OPERATIONS)
    payload = {
        "model": model.model,
        "messages": [
            {"role": "system", "content": "Planeje uma agregação sobre uma tabela. Use nomes exatos das colunas. "
             "Use string vazia nos campos dispensáveis. count conta linhas. ratio calcula 100 × soma do numerador "
             "÷ soma do denominador. Filtros são por igualdade textual. Se faltar uma definição de negócio "
             "ou a pergunta exceder essas operações, peça esclarecimento em português em texto simples."},
            {"role": "user", "content": json.dumps({"question": question, "schema": schema}, ensure_ascii=False)},
        ],
        "tools": [{"type": "function", "function": {"name": "aggregate", "strict": True,
                   "description": "Calcula uma agregação local, opcionalmente agrupada e filtrada.",
                   "parameters": {"type": "object", "properties": properties, "required": list(fields),
                                  "additionalProperties": False}}}],
        "parallel_tool_calls": False,
    }
    message = model.complete(payload)
    try:
        calls = message.get("tool_calls") or []
        if calls:
            function = calls[0]["function"]
            if function["name"] != "aggregate":
                raise ValueError
            return json.loads(function["arguments"])
        if message.get("content"):
            return message["content"]
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    raise ValueError("A IA não retornou uma operação válida.")


def suggest_indicators(model, columns, rows):
    message = model.complete({
        "model": model.model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Sugira até três indicadores úteis e distintos em português. "
             'Retorne JSON com a chave "suggestions", uma lista de objetos com "title", "topic", '
             '"assumption" (o que confirmar sobre as colunas) e "plan". O plano contém operation, column, '
             "group e denominator, com nomes exatos ou strings vazias. Para evolução mensal, "
             "use monthly: true e escolha a coluna de data em group. Operações disponíveis: "
             + ", ".join(OPERATIONS) + ". count conta linhas; ratio é 100 vezes soma da coluna dividida "
             "pela soma do denominador. Sugira apenas o que pode ser calculado com essas operações."},
            {"role": "user", "content": json.dumps(diagnosis(columns, rows), ensure_ascii=False)},
        ],
    })
    try:
        suggestions = json.loads(message["content"])["suggestions"]
        if not isinstance(suggestions, list):
            raise ValueError
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("A IA não retornou sugestões em formato válido.") from error
    valid = []
    for suggestion in suggestions[:3]:
        try:
            title, topic, assumption = (suggestion[key] for key in ("title", "topic", "assumption"))
            if not all(isinstance(value, str) and value.strip() for value in (title, topic, assumption)):
                continue
            result = aggregate(columns, rows, suggestion["plan"])
            valid.append({"title": title[:160], "topic": topic[:80], "assumption": assumption[:300],
                          "plan": result["plan"]})
        except (KeyError, TypeError, ValueError):
            continue
    if not valid:
        raise ValueError("A IA não encontrou indicadores compatíveis com os dados.")
    return valid
