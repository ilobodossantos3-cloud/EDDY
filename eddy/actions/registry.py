"""Catálogo de ações. O LLM só vê este catálogo; nunca executa código por conta própria."""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("eddy.actions")


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict | None = None


@dataclass
class ActionSpec:
    name: str
    description: str
    schema: dict
    risk: int
    func: Callable[..., ActionResult]
    taints: bool = False      # o resultado traz conteúdo externo
    family: str = "geral"
    summarize: Callable[[dict], str] | None = None

    def tool_def(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": f"[nível {self.risk}] {self.description}",
            "parameters": self.schema}}

    def describe_call(self, args: dict) -> str:
        if self.summarize:
            try:
                return self.summarize(args)
            except Exception:
                pass
        a = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.name}({a})"


@dataclass
class Ctx:
    """Contexto entregue a cada ação."""
    cfg: Any
    vault: Any = None
    emit: Callable[[str, dict], None] = lambda *_: None
    reminders: Any = None
    executor: Any = None
    llm: Any = None
    skills: Any = None
    session: Any = None
    speak: Callable[[str], None] | None = None
    extras: dict = field(default_factory=dict)


REGISTRY: dict[str, ActionSpec] = {}


def obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


def action(name: str, description: str, schema: dict | None = None, risk: int = 1,
           taints: bool = False, family: str = "geral", summarize: Callable[[dict], str] | None = None):
    def deco(fn: Callable[..., ActionResult]):
        REGISTRY[name] = ActionSpec(name, description, schema or obj(), risk, fn, taints, family, summarize)
        return fn
    return deco


_BUILTIN = ["system", "apps", "files", "web", "input_control", "screen", "routines", "vault_tools", "shell", "skills_tools"]
_loaded = False


def load_builtin_actions() -> None:
    global _loaded
    if _loaded:
        return
    for m in _BUILTIN:
        importlib.import_module(f"eddy.actions.{m}")
    _loaded = True


def load_plugins(cfg) -> list[str]:
    """Carrega só os plugins listados em config (plugins.enabled) a partir de plugins/."""
    import importlib.util
    loaded = []
    for name in cfg.get("plugins.enabled", []) or []:
        if not name.replace("_", "").replace("-", "").isalnum():
            log.warning("Nome de plugin inválido ignorado: %r", name)
            continue
        path = cfg.path("plugins") / f"{name}.py"
        if not path.exists():
            path = cfg.path("plugins") / name / "__init__.py"
        if not path.exists():
            log.warning("Plugin '%s' não encontrado.", name)
            continue
        spec = importlib.util.spec_from_file_location(f"eddy_plugin_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        loaded.append(name)
    return loaded
