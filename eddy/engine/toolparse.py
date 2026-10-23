"""Parser tolerante do protocolo de ferramentas em texto (modelos sem tool-calling nativo)."""
from __future__ import annotations

import json
import re


def _balanced_objects(text: str):
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]
                start = None


def parse_tool_json(text: str) -> tuple[str, dict] | None:
    """Devolve (nome, args) do primeiro JSON válido com chave 'tool', ou None."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    for chunk in _balanced_objects(cleaned):
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            try:
                obj = json.loads(re.sub(r",\s*([}\]])", r"\1", chunk.replace("'", '"')))
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict):
            name = obj.get("tool") or obj.get("name") or obj.get("action")
            args = obj.get("args", obj.get("arguments", {}))
            if isinstance(name, str) and isinstance(args, dict):
                return name, args
    return None


def looks_like_attempt(text: str) -> bool:
    return '"tool"' in text or "'tool'" in text
