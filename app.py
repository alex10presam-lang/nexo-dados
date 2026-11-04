"""Local portfolio dashboard. Run with python app.py."""
from dataclasses import asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from investigator import Investigation, investigate, query, seed
from model import configured_model, validate_model
from portfolio import QUALITY_CSV, QUALITY_PLANS, combine_tables, dashboard, filter_rows, quality_investigation
from tabular import LIMIT, aggregate, choose_plan, diagnosis, import_table, parse_date, profile, suggest_indicators, transform
from csv_sales import COLUMNS, MAX_BYTES, compare_sales, read_sales

ROOT = Path(__file__).resolve().parent


class Dashboard(SimpleHTTPRequestHandler):
    def __init__(self, *args, database: Path, **kwargs):
        self.database = database
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403, "Use the local dashboard address.")
            return False
        return True

    def send_json(self, status, body):
        encoded = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/api/quality-example":
            return self.send_json(200, {"content": QUALITY_CSV, "plans": QUALITY_PLANS})
        if self.path == "/modelo-vendas.csv":
            content = (ROOT / "examples" / "modelo-vendas.csv").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="modelo-vendas.csv"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path == "/api/examples":
            return self.send_json(200, [
                {"title": case["title"], "question": case["question"]}
                for case in CASES
            ])
        if self.path not in {"/", "/index.html", "/style.css", "/dashboard.js", "/tabular.js", "/ai-settings.js", "/nexo.svg"}:
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if self.path not in {"/api/investigate", "/api/csv-preview", "/api/table", "/api/ai/validate"}:
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            limit = LIMIT if self.path == "/api/table" else MAX_BYTES
            if not 0 < length <= limit * (12 if self.path == "/api/table" else 6) + 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("Solicitação inválida ou arquivo acima do limite.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Formato de solicitação inválido.")
            if self.path == "/api/ai/validate":
                return self.send_json(200, validate_model(configured_model(data.get("ai"))))
            if self.path == "/api/table":
                columns, rows, sheets, sheet = import_table(data)
                action = data.get("action")
                if data.get("second") is not None and columns:
                    columns, rows = combine_tables(columns, rows, data)
                rules = data.get("rules", [])
                if not isinstance(rules, list) or len(rules) > 20:
                    raise ValueError("Aplique até 20 correções por tabela.")
                for rule in rules:
                    rows, _ = transform(columns, rows, rule)
                if action == "preview":
                    months = []
                    if "Data" in columns:
                        index = columns.index("Data")
                        dates = (parse_date(row[index]) for row in rows)
                        months = sorted({day[:7] for day in dates if day})
                    return self.send_json(200, {"columns": profile(columns, rows), "sample": rows[:5],
                                                "count": len(rows), "sheets": sheets, "sheet": sheet,
                                                "diagnosis": diagnosis(columns, rows), "months": months})
                if action == "dashboard":
                    return self.send_json(200, dashboard(columns, rows, data))
                if action == "filter-values":
                    column = data.get("column")
                    if column not in columns:
                        raise ValueError("Escolha uma coluna válida.")
                    index = columns.index(column)
                    values = sorted({row[index] for row in rows})
                    return self.send_json(200, {"values": values[:100]})
                if action in ("quality", "quality-ai"):
                    evidence = quality_investigation(columns, rows, data.get("previous"), data.get("current"))
                    if action == "quality" and isinstance(data.get("line"), str):
                        line = data["line"]
                        line_index, date_index = columns.index("Linha"), columns.index("Data")
                        evidence["records"] = [row for row in rows if row[line_index] == line
                                               and (parse_date(row[date_index]) or "")[:7] in evidence["periods"]]
                        evidence["columns"] = columns
                    if action == "quality-ai":
                        provider = configured_model(data.get("ai"))
                        message = provider.complete({"model": provider.model, "messages": [
                            {"role": "system", "content": "Resuma a comparação em português. Use apenas a evidência agregada. "
                             "Diferencie aumento em pontos percentuais de percentual relativo. "
                             "Identifique o maior aumento comparável. Separe observações de hipóteses a verificar."},
                            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                        ]})
                        evidence["commentary"] = message.get("content") or "A IA não retornou uma interpretação."
                    return self.send_json(200, evidence)
                if action == "treatment":
                    _, preview = transform(columns, rows, data.get("rule"))
                    return self.send_json(200, preview)
                plan = data.get("plan")
                if action in ("ask", "plan", "suggest"):
                    provider = configured_model(data.get("ai"))
                    if action == "suggest":
                        return self.send_json(200, {"suggestions": suggest_indicators(provider, columns, rows)})
                    question = data.get("question")
                    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
                        raise ValueError("Digite uma pergunta com até 1.000 caracteres.")
                    if action == "plan":
                        rows = filter_rows(columns, rows, data)
                    plan = choose_plan(provider, question, profile(columns, rows))
                    if isinstance(plan, str):
                        return self.send_json(200, {"clarification": plan})
                    if action == "plan":
                        return self.send_json(200, {"plan": plan})
                elif action not in ("calculate", "calculate-scoped"):
                    raise ValueError("Selecione uma ação de análise.")
                if action == "calculate-scoped":
                    rows = filter_rows(columns, rows, data)
                return self.send_json(200, aggregate(columns, rows, plan))
            if self.path == "/api/csv-preview":
                rows = read_sales(data.get("csv"))
                return self.send_json(200, {
                    "months": sorted({row[1][:7] for row in rows}),
                    "count": len(rows), "columns": COLUMNS, "rows": rows[:5],
                })
            mode = data.get("mode")
            if mode == "demo":
                index = data.get("example")
                if type(index) is not int or not 0 <= index < len(CASES):
                    raise ValueError("Escolha um cenário da demonstração.")
                case = CASES[index]
                evidence = tuple(query(self.database, tool, *case["months"]) for tool in case["tools"])
                result = Investigation(case["answer"], evidence)
            elif mode == "csv":
                result = compare_sales(read_sales(data.get("csv")), data.get("previous"), data.get("current"))
            elif mode == "live":
                question = data.get("question")
                if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
                    raise ValueError("Digite uma pergunta com até 1.000 caracteres.")
                result = investigate(question.strip(), self.database, configured_model(data.get("ai")))
            else:
                raise ValueError("Selecione um modo de análise.")
        except ValueError as error:
            return self.send_json(400, {"error": str(error)})
        return self.send_json(200, {"mode": mode, **asdict(result)})


CASES = json.loads((ROOT / "examples" / "cases.json").read_text(encoding="utf-8"))

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        database = Path(directory) / "sales.sqlite"
        seed(database)
        port = int(os.getenv("PORT", "8765"))
        handler = partial(Dashboard, database=database)
        with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
            print(f"Nexo Dados em http://127.0.0.1:{port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
