import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from app import Dashboard
from investigator import seed


class DashboardTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        database = Path(folder.name) / "sales.sqlite"
        seed(database)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Dashboard, database=database))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

    def request(self, path, body=None):
        request = Request(self.base + path)
        if body is not None:
            request.data = json.dumps(body).encode()
            request.add_header("Content-Type", "application/json")
        return build_opener(ProxyHandler({})).open(request, timeout=5)

    def test_rejects_unexpected_host(self):
        request = Request(self.base + "/api/examples", headers={"Host": "other.example"})
        with self.assertRaises(HTTPError) as raised:
            build_opener(ProxyHandler({})).open(request, timeout=5)
        raised.exception.close()
        self.assertEqual(raised.exception.code, 403)

    def test_dashboard_and_all_demo_cases(self):
        with self.request("/") as response:
            self.assertIn("O que mudou nas vendas?", response.read().decode())
        with self.request("/api/examples") as response:
            self.assertEqual(len(json.load(response)), 3)
        for example in range(3):
            with self.request("/api/investigate", {"mode": "demo", "example": example}) as response:
                result = json.load(response)
            self.assertEqual(result["mode"], "demo")
            self.assertTrue(result["evidence"][0]["sql"])
            if example == 0:
                self.assertIn("R$ 150", result["answer"])
                self.assertEqual(result["evidence"][1]["rows"][0]["variacao_centavos"], -15000)
            if example == 1:
                self.assertEqual([row["pedidos"] for row in result["evidence"][0]["rows"]], [8, 10])
            if example == 2:
                self.assertEqual(result["evidence"][0]["missing"], ["2025-11"])

    def test_live_without_configuration_reports_error(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            with self.assertRaises(HTTPError) as raised:
                self.request("/api/investigate", {"mode": "live", "question": "Qual foi a queda?"})
        with raised.exception as response:
            self.assertEqual(response.code, 400)
            self.assertIn("OPENAI_API_KEY", json.load(response)["error"])
