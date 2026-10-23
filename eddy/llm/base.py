"""Interface comum dos modelos (API ou locais)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Erro de modelo com mensagem já em português e sem segredos."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    name: str
    supports_tools: bool
    vision: bool

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw: Any) -> LLMResponse: ...
