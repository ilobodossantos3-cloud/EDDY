"""Gestor de perfis de modelo, com troca em runtime e fallback para local."""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..config import Config
from .base import LLMError, LLMResponse

log = logging.getLogger("eddy.llm")


class LLMManager:
    def __init__(self, cfg: Config, on_fallback: Callable[[str, str], None] | None = None):
        self.cfg = cfg
        self.active = cfg.get("llm.active")
        self._cache: dict[str, Any] = {}
        self.on_fallback = on_fallback
        self.using_fallback = False

    # -- perfis ------------------------------------------------------
    def profiles(self) -> list[str]:
        return list((self.cfg.get("llm.profiles", {}) or {}).keys())

    def _build(self, name: str):
        prof = (self.cfg.get("llm.profiles", {}) or {}).get(name)
        if prof is None:
            raise LLMError(f"Perfil de modelo '{name}' não existe. Perfis: {', '.join(self.profiles())}")
        t = prof.get("type")
        if t == "openai_compat":
            from .openai_compat import OpenAICompatProvider
            key = Config.secret(prof.get("api_key_env", ""))
            return OpenAICompatProvider(name, prof, key, float(self.cfg.get("llm.timeout_s", 60)),
                                        int(self.cfg.get("llm.retries", 2)))
        if t == "llama_cpp":
            from .llama_cpp_provider import LlamaCppProvider
            return LlamaCppProvider(name, prof, self.cfg.root)
        if t == "transformers":
            from .transformers_provider import TransformersProvider
            return TransformersProvider(name, prof, self.cfg.root)
        raise LLMError(f"Tipo de perfil desconhecido: {t!r}")

    def get(self, name: str | None = None):
        name = name or self.active
        if name not in self._cache:
            self._cache[name] = self._build(name)
        return self._cache[name]

    def switch(self, name: str):
        self.get(name)  # valida
        self.active = name
        self.using_fallback = False
        return self.get(name)

    @property
    def provider(self):
        return self.get(self.active)

    def is_cloud(self) -> bool:
        try:
            return bool(getattr(self.get(self.using_fallback and self.cfg.get("llm.fallback") or self.active), "is_cloud", False))
        except LLMError:
            return False

    # -- chamada com fallback ---------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw: Any) -> tuple[LLMResponse, Any]:
        """Devolve (resposta, provider usado)."""
        primary = self.get(self.active)
        try:
            return primary.chat(messages, tools, **kw), primary
        except LLMError as e:
            fb = self.cfg.get("llm.fallback") or ""
            if not fb or fb == self.active:
                raise
            log.warning("Modelo '%s' falhou (%s); a usar '%s'", self.active, e, fb)
            try:
                fallback = self.get(fb)
                result = fallback.chat(messages, tools, **kw), fallback
            except LLMError as e2:
                raise LLMError(f"Modelo '{self.active}': {e} | Reserva '{fb}': {e2}") from e2
            if self.on_fallback and not self.using_fallback:
                self.on_fallback(self.active, fb)
            self.using_fallback = True
            return result
