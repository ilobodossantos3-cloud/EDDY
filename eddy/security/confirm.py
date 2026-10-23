"""Confirmações presas a UMA ação com argumentos exatos, de uso único e com expiração."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_WORDS = ["lua", "rio", "pedra", "vento", "sol", "mar", "ouro", "cedro", "neve", "fogo", "areia", "ponte",
          "nuvem", "farol", "trigo", "prata"]


def action_hash(name: str, args: dict) -> str:
    blob = json.dumps({"n": name, "a": args}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class Pending:
    id: str
    name: str
    args: dict
    summary: str
    level: int
    hash: str
    code: str
    expires: float
    event: threading.Event = field(default_factory=threading.Event)
    accepted: bool = False
    used: bool = False


class ConfirmManager:
    def __init__(self, timeout_s: float = 30, emit: Callable[[str, dict], None] | None = None,
                 allow_voice: bool = True):
        self.timeout_s = timeout_s
        self.emit = emit or (lambda *_: None)
        self.allow_voice = allow_voice
        self._pending: dict[str, Pending] = {}
        self._lock = threading.Lock()

    def request(self, name: str, args: dict, summary: str, level: int) -> bool:
        """Bloqueia até haver resposta ou expirar. Devolve True só se aceite pelo utilizador."""
        pid = secrets.token_hex(6)
        code = " ".join(secrets.choice(_WORDS) for _ in range(2))
        p = Pending(pid, name, dict(args), summary, level, action_hash(name, args), code,
                    time.time() + self.timeout_s)
        with self._lock:
            self._pending[pid] = p
        self.emit("confirm_request", {"id": pid, "action": name, "args": args, "summary": summary,
                                      "level": level, "code": code, "timeout_s": self.timeout_s})
        ok = p.event.wait(self.timeout_s)
        with self._lock:
            self._pending.pop(pid, None)
        accepted = ok and p.accepted and time.time() <= p.expires
        self.emit("confirm_done", {"id": pid, "accepted": accepted})
        return accepted

    def resolve(self, pid: str, accept: bool, source: str = "hud", spoken: str | None = None) -> bool:
        """`source` ∈ {'hud','voice'}. Por voz, é preciso repetir o código de 2 palavras."""
        with self._lock:
            p = self._pending.get(pid)
            if p is None or p.used or time.time() > p.expires:
                return False
            if accept and source == "voice":
                if not self.allow_voice or not spoken or p.code not in " ".join(spoken.lower().split()):
                    return False
            elif source not in ("hud", "voice"):
                return False
            p.used = True
            p.accepted = bool(accept)
        p.event.set()
        return True

    def resolve_voice(self, spoken: str) -> bool:
        """Tenta resolver a confirmação pendente mais recente com o que foi dito."""
        spoken_n = " ".join(spoken.lower().split())
        with self._lock:
            ids = [i for i, p in self._pending.items() if not p.used]
        for pid in reversed(ids):
            p = self._pending.get(pid)
            if p and p.code in spoken_n and any(w in spoken_n for w in ("confirm", "sim", "avança", "avanca", "autoriz")):
                return self.resolve(pid, True, "voice", spoken)
            if p and any(w in spoken_n for w in ("cancela", "não", "nao", "pára", "para tudo")):
                return self.resolve(pid, False, "voice", spoken)
        return False

    def cancel_all(self) -> None:
        with self._lock:
            items = list(self._pending.values())
        for p in items:
            p.used = True
            p.accepted = False
            p.event.set()

    def pending(self) -> list[Pending]:
        with self._lock:
            return list(self._pending.values())
