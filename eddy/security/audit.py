"""Registo de auditoria append-only (JSON Lines), sem segredos."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .sanitize import redact


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _clean(obj: Any) -> Any:
        if isinstance(obj, str):
            return redact(obj)[:500]
        if isinstance(obj, dict):
            return {k: AuditLog._clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [AuditLog._clean(v) for v in obj][:20]
        return obj

    def write(self, **fields: Any) -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **self._clean(fields)}
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for l in lines:
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                pass
        return out
