"""Provider para qualquer API compatível com OpenAI (Inception, NVIDIA NIM, OpenRouter, Ollama, LM Studio, llama.cpp server)."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .base import LLMError, LLMResponse, ToolCall


class OpenAICompatProvider:
    def __init__(self, name: str, profile: dict, api_key: str | None, timeout_s: float = 60,
                 retries: int = 2, transport: httpx.BaseTransport | None = None):
        self.name = name
        self.base_url = str(profile.get("base_url", "")).rstrip("/")
        self.model = profile.get("model", "")
        self.supports_tools = bool(profile.get("supports_tools", False))
        self.vision = bool(profile.get("vision", False))
        self._api_key = api_key
        self.is_cloud = not any(h in self.base_url for h in ("localhost", "127.0.0.1", "[::1]"))
        self.retries = max(0, int(retries))
        self.extra = profile.get("extra_body", {}) or {}
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=5.0), transport=transport)
        if self.base_url.startswith("http://") and self.is_cloud:
            raise LLMError("URL de API sem HTTPS recusado por segurança.")

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw: Any) -> LLMResponse:
        if self.is_cloud and not self._api_key:
            raise LLMError(f"Falta a chave de API para o perfil '{self.name}'. Põe-na no ficheiro .env.")
        body: dict[str, Any] = {"model": self.model, "messages": messages, **self.extra}
        for k in ("temperature", "max_tokens", "top_p"):
            if k in kw and kw[k] is not None:
                body[k] = kw[k]
        if tools and self.supports_tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        url = f"{self.base_url}/chat/completions"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self._client.post(url, headers=self._headers(), json=body)
                if r.status_code == 401 or r.status_code == 403:
                    raise LLMError("A API recusou a chave (401/403). Verifica a chave no .env.")
                if r.status_code == 402:
                    raise LLMError("A API diz que não tens créditos (402).")
                if r.status_code == 429 or r.status_code >= 500:
                    last = LLMError(f"A API está sobrecarregada ou com erro ({r.status_code}).")
                    time.sleep(min(2 ** attempt * 0.5, 4))
                    continue
                if r.status_code >= 400:
                    raise LLMError(f"Erro da API ({r.status_code}): {self._safe(r.text)}")
                return self._parse(r.json())
            except LLMError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = LLMError(f"Sem ligação ao modelo ({type(e).__name__}).")
                time.sleep(min(2 ** attempt * 0.5, 4))
        raise last or LLMError("Falha desconhecida ao chamar o modelo.")

    @staticmethod
    def _safe(text: str) -> str:
        return text[:300].replace("\n", " ")

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("Resposta inesperada da API.") from e
        calls: list[ToolCall] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))
        content = msg.get("content") or ""
        if isinstance(content, list):  # alguns servidores devolvem blocos
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
        return LLMResponse(text=content, tool_calls=calls, usage=data.get("usage"))
