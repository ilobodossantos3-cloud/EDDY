from __future__ import annotations

import random
from pathlib import Path

import yaml

_DATA: dict[str, list[str]] | None = None


def _load() -> dict[str, list[str]]:
    global _DATA
    if _DATA is None:
        _DATA = yaml.safe_load((Path(__file__).parent / "lines.yaml").read_text(encoding="utf-8")) or {}
    return _DATA


def pick(key: str, sarcasm: int = 2, rng: random.Random | None = None) -> str:
    """Escolhe uma frase respeitando a intensidade de sarcasmo (prefere as do nível mais alto permitido)."""
    rng = rng or random
    eligible: list[tuple[int, str]] = []
    for raw in _load().get(key, []):
        lvl, _, text = raw.partition("|")
        if lvl.isdigit() and int(lvl) <= sarcasm:
            eligible.append((int(lvl), text))
    if not eligible:
        return ""
    top = max(l for l, _ in eligible)
    top_opts = [t for l, t in eligible if l == top]
    return rng.choice(top_opts if rng.random() < 0.7 else [t for _, t in eligible])
