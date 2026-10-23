"""Lembretes persistentes (JSON) com um fio que os dispara à hora certa."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable


class Reminders:
    def __init__(self, path: Path, on_fire: Callable[[str], None]):
        self.path = Path(path)
        self.on_fire = on_fire
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    def _load(self) -> None:
        try:
            self._items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._items = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, when_ts: float, text: str) -> dict:
        item = {"id": uuid.uuid4().hex[:8], "ts": float(when_ts), "text": text[:200]}
        with self._lock:
            self._items.append(item)
            self._save()
        return item

    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self._items, key=lambda i: i["ts"])

    def tick(self, now: float | None = None) -> int:
        now = now or time.time()
        due = []
        with self._lock:
            keep = []
            for i in self._items:
                (due if i["ts"] <= now else keep).append(i)
            if due:
                self._items = keep
                self._save()
        for i in due:
            try:
                self.on_fire(i["text"])
            except Exception:
                pass
        return len(due)

    def start(self) -> None:
        if self._thread:
            return
        def loop():
            while not self._stop.wait(1.0):
                self.tick()
        self._thread = threading.Thread(target=loop, daemon=True, name="reminders")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
