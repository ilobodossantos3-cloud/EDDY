"""Carrega config.yaml + .env. Acesso por caminho: cfg.get("voice.tts.fish.model")."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    def __init__(self, data: dict, root: Path = ROOT):
        self.data = data
        self.root = Path(root)

    @classmethod
    def load(cls, path: str | Path | None = None, overrides: dict | None = None) -> "Config":
        root = ROOT
        cfg_path = Path(path) if path else root / "config.yaml"
        load_dotenv(root / ".env", override=False)
        data: dict = {}
        if cfg_path.exists():
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if overrides:
            data = _deep_merge(data, overrides)
        return cls(data, root)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        cur = self.data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def path(self, rel: str | Path) -> Path:
        """Caminho relativo à raiz do projeto (ou absoluto se já o for)."""
        p = Path(os.path.expanduser(str(rel)))
        return p if p.is_absolute() else (self.root / p)

    @staticmethod
    def secret(env_name: str) -> str | None:
        """Lê um segredo do ambiente. Nunca guardar em logs."""
        return os.environ.get(env_name) if env_name else None
