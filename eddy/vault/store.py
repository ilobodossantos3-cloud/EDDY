"""Vault em Markdown (compatível com Obsidian). Só ficheiros, sem base de dados."""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..security.safe_paths import PathDenied, resolve_inside
from ..security.sanitize import redact

WIKILINK = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
TOKEN = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)
MAX_NOTE = 200_000


def _tok(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text)]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            meta: dict = {}
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return meta, text[end + 4:].lstrip("\n")
    return {}, text


class VaultStore:
    DIRS = ("raw", "wiki", "outputs")

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        for d in self.DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._docs: dict[str, dict] = {}
        self._idf: dict[str, float] = {}
        self._avg = 1.0
        self._built = 0.0

    # ---- caminhos seguros ------------------------------------------
    def _p(self, rel: str, must_exist: bool = False) -> Path:
        rel = str(rel).replace("\\", "/")
        if re.match(r"^[A-Za-z]:", rel) or rel.startswith("//"):
            raise PathDenied("Usa caminhos relativos ao vault (ex.: wiki/nota.md).")
        if rel.startswith("/"):
            rel = rel.lstrip("/")
            if rel.split("/")[0] not in self.DIRS:        # "/etc/passwd" etc.: recusado
                raise PathDenied("Usa caminhos relativos ao vault (ex.: wiki/nota.md).")
        if not rel.endswith(".md") and "." not in Path(rel).name:
            rel += ".md"
        p = resolve_inside(rel, [self.root], must_exist=must_exist)
        if p.suffix.lower() != ".md" and p.suffix.lower() != ".json" and p.suffix.lower() != ".txt":
            raise PathDenied("O vault só guarda notas Markdown.")
        if ".obsidian" in p.parts:
            raise PathDenied("Pasta de configuração do Obsidian protegida.")
        return p

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    # ---- operações -------------------------------------------------
    def read(self, path: str) -> str:
        return self._p(path, must_exist=True).read_text(encoding="utf-8", errors="replace")

    def write(self, path: str, content: str, mode: str = "append") -> str:
        if len(content) > MAX_NOTE:
            raise PathDenied("Nota demasiado grande.")
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = redact(content)  # nunca gravar segredos no vault
        with self._lock:
            if mode == "overwrite" or not p.exists():
                p.write_text(content, encoding="utf-8")
            else:
                with open(p, "a", encoding="utf-8") as f:
                    f.write(("\n" if not content.startswith("\n") else "") + content + "\n")
        self._built = 0.0  # invalida índice
        return self.rel(p)

    def list(self, folder: str = "") -> list[str]:
        base = self.root if not folder else resolve_inside(folder.strip("/\\"), [self.root], must_exist=True)
        return sorted(self.rel(p) for p in base.rglob("*.md") if ".obsidian" not in p.parts)

    def new_note(self, folder: str, title: str, body: str, tags: list[str] | None = None, source: str = "eddy") -> str:
        slug = re.sub(r"[^\w\-]+", "-", title.lower()).strip("-")[:60] or "nota"
        fm = f"---\ncreated: {time.strftime('%Y-%m-%d %H:%M')}\ntags: {', '.join(tags or [])}\nsource: {source}\n---\n\n"
        return self.write(f"{folder}/{slug}.md", fm + body, mode="overwrite")

    def daily_log(self, request: str, reply: str) -> None:
        day = time.strftime("%Y-%m-%d")
        self.write(f"raw/{day}.md", f"- {time.strftime('%H:%M')} **tu:** {request}\n  **eddy:** {reply}", mode="append")

    # ---- índice / grafo / pesquisa ----------------------------------
    def build_index(self, force: bool = False) -> None:
        if not force and self._built and time.time() - self._built < 30:
            return
        docs: dict[str, dict] = {}
        for path in self.list():
            try:
                text = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            links = sorted({l.strip() for l in WIKILINK.findall(body)})
            toks = _tok(path + " " + body)
            docs[path] = {"meta": meta, "body": body, "links": links, "tf": Counter(toks), "len": len(toks)}
        df: Counter = Counter()
        for d in docs.values():
            df.update(d["tf"].keys())
        n = max(len(docs), 1)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self._avg = sum(d["len"] for d in docs.values()) / n if docs else 1.0
        self._docs = docs
        self._built = time.time()

    def search(self, query: str, k: int = 5) -> list[dict]:
        self.build_index()
        q = _tok(query)
        if not q:
            return []
        k1, b = 1.5, 0.75
        scores: list[tuple[float, str]] = []
        for path, d in self._docs.items():
            s = 0.0
            for t in q:
                f = d["tf"].get(t, 0)
                if f:
                    s += self._idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * d["len"] / self._avg))
            if s > 0:
                scores.append((s, path))
        scores.sort(reverse=True)
        out = []
        for s, path in scores[:k]:
            body = self._docs[path]["body"].strip().replace("\n", " ")
            idx = max(0, min((body.lower().find(q[0]) if body.lower().find(q[0]) >= 0 else 0) - 40, len(body)))
            out.append({"path": path, "score": round(s, 3), "snippet": body[idx:idx + 160]})
        return out

    def context_for(self, query: str, n: int = 5, max_chars: int = 3000) -> str:
        parts, used = [], 0
        for h in self.search(query, k=n):
            chunk = f"[{h['path']}] {h['snippet']}"
            if used + len(chunk) > max_chars:
                break
            parts.append(chunk)
            used += len(chunk)
        return "\n".join(parts)

    def graph(self) -> dict:
        self.build_index()
        stems = {Path(p).stem.lower(): p for p in self._docs}
        edges, back = [], defaultdict(list)
        broken = []
        for p, d in self._docs.items():
            for l in d["links"]:
                tgt = stems.get(Path(l).stem.lower())
                if tgt:
                    edges.append((p, tgt))
                    back[tgt].append(p)
                else:
                    broken.append((p, l))
        linked = {a for a, _ in edges} | {b for _, b in edges}
        orphans = [p for p in self._docs if p not in linked]
        return {"nodes": list(self._docs), "edges": edges, "backlinks": dict(back), "orphans": orphans, "broken": broken}

    def save_index(self) -> Path:
        g = self.graph()
        out = self.root / ".eddy-index.json"
        out.write_text(json.dumps({"updated": time.strftime("%Y-%m-%d %H:%M"), "notes": len(g["nodes"]),
                                   "edges": g["edges"], "orphans": g["orphans"]}, ensure_ascii=False), encoding="utf-8")
        return out

    def count(self) -> int:
        return len(self.list())
