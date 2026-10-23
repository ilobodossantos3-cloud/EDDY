"""Modelos GGUF locais (Hugging Face) via llama-cpp-python."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import LLMError, LLMResponse


class LlamaCppProvider:
    is_cloud = False

    def __init__(self, name: str, profile: dict, root: Path):
        self.name = name
        self.supports_tools = bool(profile.get("supports_tools", False))
        self.vision = False
        self._profile = profile
        self._root = root
        self._llm = None

    def _load(self):
        if self._llm is not None:
            return self._llm
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError as e:
            raise LLMError(
                "Falta o 'llama-cpp-python'. Instala com:  pip install llama-cpp-python  "
                "(no Windows pode precisar de 'Microsoft C++ Build Tools'; alternativa: usa o Ollama ou o LM Studio)."
            ) from e
        p = Path(str(self._profile.get("model_path", "")))
        p = p if p.is_absolute() else self._root / p
        if not p.exists():
            raise LLMError(f"Modelo GGUF não encontrado em '{p}'. Descarrega com: python scripts/download_model.py --repo <repo> --file <ficheiro.gguf>")
        self._llm = Llama(
            model_path=str(p),
            n_ctx=int(self._profile.get("n_ctx", 8192)),
            n_gpu_layers=int(self._profile.get("n_gpu_layers", -1)),
            chat_format=self._profile.get("chat_format"),
            verbose=False,
        )
        return self._llm

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw: Any) -> LLMResponse:
        llm = self._load()
        out = llm.create_chat_completion(
            messages=messages,
            temperature=kw.get("temperature", 0.6),
            max_tokens=kw.get("max_tokens", 512),
        )
        return LLMResponse(text=out["choices"][0]["message"].get("content") or "", usage=out.get("usage"))
