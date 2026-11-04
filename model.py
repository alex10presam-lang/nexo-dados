"""OpenAI Chat Completions adapter. The model can request one tool per turn."""
from dataclasses import asdict
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from investigator import Call, Clarification, Evidence, TOOLS

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "ollama": "http://127.0.0.1:11434/v1/chat/completions",
    "claude": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}


def claude_request(payload):
    messages = payload["messages"]
    request = {
        "model": payload["model"], "max_tokens": 2048,
        "system": "\n\n".join(message["content"] for message in messages if message["role"] == "system"),
        "messages": [message for message in messages if message["role"] != "system"],
    }
    if payload.get("tools"):
        request["tools"] = [
            {"name": function["name"], "description": function["description"],
             "input_schema": function["parameters"]}
            for function in (tool["function"] for tool in payload["tools"])
        ]
        request["tool_choice"] = {"type": "any" if payload.get("tool_choice") == "required" else "auto",
                                  "disable_parallel_tool_use": True}
    if payload.get("response_format", {}).get("type") == "json_object":
        request["tools"] = [{"name": "return_json", "description": "Retorne o objeto JSON solicitado.",
                             "input_schema": {"type": "object", "additionalProperties": True}}]
        request["tool_choice"] = {"type": "tool", "name": "return_json"}
    return request


def claude_message(response, structured):
    content = response["content"]
    if structured:
        for block in content:
            if block["type"] == "tool_use" and block["name"] == "return_json":
                return {"content": json.dumps(block["input"], ensure_ascii=False)}
    return {
        "content": "\n".join(block["text"] for block in content if block["type"] == "text"),
        "tool_calls": [{"function": {"name": block["name"], "arguments": json.dumps(block["input"])}}
                       for block in content if block["type"] == "tool_use"],
    }


class OpenAIModel:
    def __init__(self, key: str, model: str, provider: str = "openai"):
        self.key = key
        self.model = model
        self.provider = provider

    def __call__(self, question: str, history: tuple[Evidence, ...]) -> Call | Clarification | str:
        messages = [
            {"role": "system", "content": (
                "Você investiga vendas sintéticas de agosto a outubro de 2025. "
                "Quando nenhum mês for identificável, use clarify_period antes de consultar. "
                "Use o ano 2025 se omitido. Para um mês explícito sem referência, "
                "compare com o mês anterior. Comece por compare e aprofunde por categoria "
                "ou região quando fizer sentido. Responda em português, cite números "
                "retornados, divida valores em centavos por 100 para exibir reais e "
                "separe contribuição matemática de hipóteses sobre causas. "
                "As evidências enviadas são resultados de ferramentas já executadas."
            )},
            {"role": "user", "content": question},
        ]
        if history:
            messages.append({"role": "system", "content": json.dumps(
                [asdict(evidence) for evidence in history], ensure_ascii=False
            )})
        tools = [{"type": "function", "function": {
            "name": name, "description": description, "strict": True,
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "previous": {"type": "string", "description": "Mês anterior AAAA-MM"},
                    "current": {"type": "string", "description": "Mês atual AAAA-MM"},
                },
                "required": ["previous", "current"],
            },
        }} for name, description in TOOLS.items()]
        tools.append({"type": "function", "function": {
            "name": "clarify_period",
            "description": "Solicita os meses quando a pergunta não permite identificar o período.",
            "strict": True,
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        }})
        payload = {"model": self.model, "messages": messages, "tools": tools,
                   "parallel_tool_calls": False, "tool_choice": "auto" if history else "required"}
        message = self.complete(payload)
        try:
            calls = message.get("tool_calls") or []
            if calls:
                function = calls[0]["function"]
                arguments = json.loads(function["arguments"])
                if function["name"] == "clarify_period":
                    return Clarification(**arguments)
                return Call(function["name"], **arguments)
            return message.get("content") or ""
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ValueError("O modelo devolveu uma resposta inválida. Tente novamente.") from error

    def complete(self, payload):
        endpoint = ENDPOINTS[self.provider]
        headers = {"Content-Type": "application/json"}
        structured = payload.get("response_format", {}).get("type") == "json_object"
        if self.provider == "claude":
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            payload = claude_request(payload)
        elif self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        if self.provider in ("ollama", "gemini", "deepseek"):
            payload = {key: value for key, value in payload.items() if key != "parallel_tool_calls"}
            if self.provider == "ollama":
                payload.pop("tool_choice", None)
            if "tools" in payload:
                payload["tools"] = [
                    {**tool, "function": {key: value for key, value in tool["function"].items() if key != "strict"}}
                    for tool in payload["tools"]
                ]
        request = Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        try:
            with urlopen(request, timeout=25) as response:
                data = json.load(response)
            if self.provider == "claude":
                return claude_message(data, structured)
            return data["choices"][0]["message"]
        except HTTPError as error:
            details = {
                401: "Chave recusada. Confira a credencial do provedor.",
                403: "Acesso recusado. Confira as permissões da chave e do modelo.",
                404: "Modelo não encontrado. Confira o identificador e o acesso ao modelo.",
                429: "Limite ou cota do provedor atingido. Confira o saldo ou tente novamente.",
                400: "O provedor recusou a solicitação. Confira o modelo e o suporte ao recurso solicitado.",
            }
            raise ValueError(details.get(error.code, f"A API retornou HTTP {error.code}. Tente novamente.")) from error
        except (URLError, TimeoutError) as error:
            message = ("O Ollama local não respondeu. Confira se o serviço está rodando na porta 11434."
                       if self.provider == "ollama" else "Falha de conexão com a API. Tente novamente.")
            raise ValueError(message) from error
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ValueError("O modelo devolveu uma resposta inválida. Tente novamente.") from error


def configured_model(config):
    if config is None:
        config = {"provider": "openai", "key": os.getenv("OPENAI_API_KEY", ""),
                  "model": os.getenv("OPENAI_MODEL", "")}
        if not config["key"] or not config["model"]:
            raise ValueError("Abra Configuração de IA ou configure OPENAI_API_KEY e OPENAI_MODEL no ambiente.")
    if not isinstance(config, dict) or not isinstance(config.get("provider"), str) or config["provider"] not in ENDPOINTS:
        raise ValueError("Selecione um provedor de IA disponível.")
    model, key = config.get("model"), config.get("key", "")
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 160:
        raise ValueError("Informe o identificador do modelo.")
    provider = config["provider"]
    if provider != "ollama" and (not isinstance(key, str) or not 1 <= len(key.strip()) <= 512
                                 or any(not 33 <= ord(char) <= 126 for char in key.strip())):
        raise ValueError("Informe uma chave do provedor, sem espaços internos.")
    return OpenAIModel(key.strip() if provider != "ollama" else "", model.strip(), provider)


def validate_model(provider):
    provider.complete({
        "model": provider.model,
        "messages": [{"role": "user", "content": "Responda apenas OK."}],
    })
    tool = {"type": "function", "function": {
        "name": "connection_check", "description": "Confirma que o modelo aceita ferramentas.",
        "parameters": {"type": "object", "properties": {}},
    }}
    warnings = []
    tools_ok = False
    try:
        message = provider.complete({
            "model": provider.model, "tools": [tool],
            "messages": [{"role": "user", "content": "Chame connection_check para confirmar a conexão."}],
        })
        calls = message.get("tool_calls") or []
        tools_ok = any(call.get("function", {}).get("name") == "connection_check" for call in calls)
    except ValueError:
        warnings.append("O teste de ferramentas não foi concluído.")
    json_ok = False
    try:
        structured = provider.complete({
            "model": provider.model, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": 'Retorne somente JSON com {"ok": true}.'}],
        })
        decoded = json.loads(structured.get("content") or "")
        json_ok = isinstance(decoded, dict) and decoded.get("ok") is True
    except (ValueError, TypeError):
        warnings.append("O teste de resposta estruturada não foi concluído.")
    return {"connected": True, "tools": tools_ok, "json": json_ok, "warning": " ".join(warnings)}
