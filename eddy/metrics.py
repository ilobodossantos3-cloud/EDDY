"""Métricas guardadas como notas Markdown em vault/raw/metricas/*.md (linhas 'chave: valor' + 'date: AAAA-MM-DD')."""
from __future__ import annotations

import re
from pathlib import Path

_LINE = re.compile(r"^\s*([A-Za-zÀ-ÿ_ ]+?)\s*:\s*(-?\d+(?:[.,]\d+)?)\s*$")
_DATE = re.compile(r"^\s*date\s*:\s*(\d{4}-\d{2}-\d{2})\s*$", re.I)


def read_history(vault_root: Path) -> list[dict]:
    folder = Path(vault_root) / "raw" / "metricas"
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for f in sorted(folder.glob("*.md")):
        date, vals = f.stem, {}
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _DATE.match(line)
            if m:
                date = m.group(1)
                continue
            m = _LINE.match(line)
            if m and m.group(1).strip().lower() != "date":
                vals[m.group(1).strip().lower()] = float(m.group(2).replace(",", "."))
        if vals:
            rows.append({"date": date, "values": vals})
    rows.sort(key=lambda r: r["date"])
    return rows


def latest(vault_root: Path) -> dict[str, dict]:
    hist = read_history(vault_root)
    out: dict[str, dict] = {}
    names = {k for r in hist for k in r["values"]}
    for k in names:
        series = [(r["date"], r["values"][k]) for r in hist if k in r["values"]]
        cur = series[-1][1]
        prev = series[-2][1] if len(series) > 1 else None
        out[k] = {"value": cur, "delta": None if prev is None else cur - prev, "series": [v for _, v in series][-20:]}
    return out
