import json
import urllib.error
import urllib.request
import urllib.parse
import uuid


class OpenAICompatClient:
    def __init__(self, config):
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    def _build_url(self, path):
        parsed = urllib.parse.urlparse(self.base_url)
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/v1"):
            full_path = base_path + path
        else:
            full_path = base_path + "/v1" + path
        return urllib.parse.urlunparse(parsed._replace(path=full_path))

    def _make_request(self, url, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        if self.config.api_key:
            request.add_header("Authorization", f"Bearer {self.config.api_key}")
        return request

    def check_connection(self):
        try:
            request = self._make_request(self._build_url("/models"))
            resp = urllib.request.urlopen(request, timeout=5)
            try:
                data = json.loads(resp.read())
            finally:
                resp.close()
            return True, [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        except Exception:
            return False, []

    def check_model(self, model, available_models=None):
        models = available_models or self.check_connection()[1]
        if not models:
            return True
        names = set(models)
        return model in names

    def _prepare_messages(self, messages):
        prepared = []
        for msg in messages:
            msg = dict(msg)
            if msg.get("tool_calls"):
                normalized = []
                for tc in msg["tool_calls"]:
                    tc = dict(tc)
                    func = dict(tc.get("function", {}))
                    args = func.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            func["arguments"] = json.loads(args)
                        except json.JSONDecodeError:
                            func["arguments"] = {"raw": args}
                    normalized.append({
                        "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                        "type": "function",
                        "function": func,
                    })
                msg["tool_calls"] = normalized
            prepared.append(msg)
        return prepared

    def chat(self, model, messages, tools=None, stream=True):
        payload = {
            "model": model,
            "messages": self._prepare_messages(messages),
            "stream": stream,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        request = self._make_request(self._build_url("/chat/completions"), payload)
        response = urllib.request.urlopen(request, timeout=3600)
        if not stream:
            try:
                return json.loads(response.read())
            finally:
                response.close()
        return response

    def chat_sync(self, model, messages, tools=None):
        return self.chat(model=model, messages=messages, tools=tools, stream=False)
