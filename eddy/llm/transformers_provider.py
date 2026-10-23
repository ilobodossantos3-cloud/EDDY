"""Modelos locais em formato Hugging Face (safetensors) via transformers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import LLMError, LLMResponse


class TransformersProvider:
    is_cloud = False

    def __init__(self, name: str, profile: dict, root: Path):
        self.name = name
        self.supports_tools = bool(profile.get("supports_tools", False))
        self.vision = False
        self._profile = profile
        self._root = root
        self._model = None
        self._tok = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except ImportError as e:
            raise LLMError("Faltam 'transformers' e 'torch'. Instala: pip install transformers torch accelerate") from e
        p = Path(str(self._profile.get("model_path", "")))
        p = p if p.is_absolute() else self._root / p
        if not p.exists():
            raise LLMError(f"Modelo não encontrado em '{p}'. Usa: python scripts/download_model.py --repo <repo>")
        kw: dict[str, Any] = {"device_map": self._profile.get("device", "auto")}
        dt = self._profile.get("dtype", "auto")
        kw["torch_dtype"] = "auto" if dt == "auto" else getattr(torch, dt)
        if self._profile.get("load_in_4bit"):
            try:
                from transformers import BitsAndBytesConfig  # type: ignore
                kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
            except Exception:
                pass
        self._tok = AutoTokenizer.from_pretrained(str(p))
        self._model = AutoModelForCausalLM.from_pretrained(str(p), **kw)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw: Any) -> LLMResponse:
        self._load()
        tok, model = self._tok, self._model
        ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(model.device)
        out = model.generate(ids, max_new_tokens=kw.get("max_tokens", 512), do_sample=True,
                             temperature=kw.get("temperature", 0.6))
        text = tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True)
        return LLMResponse(text=text)
