"""Ficheiros e pastas — só dentro das pastas permitidas (+ vault). Apagar vai para a Reciclagem."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..security.safe_paths import PathDenied, expand_roots, resolve_inside
from .registry import ActionResult, Ctx, action, obj

IS_WIN = sys.platform.startswith("win")
EXEC_EXT = {".exe", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi", ".msp",
            ".lnk", ".scr", ".com", ".jar", ".py", ".pyw", ".sh", ".reg", ".dll", ".hta", ".cpl", ".app", ".appimage"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".ini", ".xml", ".html", ".htm", ".tex",
            ".py", ".js", ".ts", ".c", ".h", ".cpp", ".java", ".rs", ".go", ".toml", ".sql", ".rst"}
_PATH = {"type": "string", "minLength": 1, "maxLength": 400}


def roots(ctx: Ctx) -> list[Path]:
    out = expand_roots(ctx.cfg.get("security.allowed_folders", []) or [])
    if ctx.vault is not None:
        out.append(Path(ctx.vault.root).resolve())
    return out


def _p(ctx: Ctx, path: str, must_exist: bool = True) -> Path:
    return resolve_inside(path, roots(ctx), must_exist=must_exist)


def _err(e: Exception) -> ActionResult:
    if isinstance(e, PathDenied):
        return ActionResult(False, str(e))
    return ActionResult(False, f"Não consegui ({type(e).__name__}).")


@action("files_list", "Lista o conteúdo de uma pasta permitida.", obj({"folder": _PATH}, ["folder"]),
        risk=0, family="ficheiros", taints=True)
def files_list(ctx: Ctx, folder: str) -> ActionResult:
    try:
        p = _p(ctx, folder)
        if not p.is_dir():
            return ActionResult(False, "Isso não é uma pasta.")
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:40]
        names = [("[pasta] " if i.is_dir() else "") + i.name for i in items]
        return ActionResult(True, f"{len(items)} itens: " + ", ".join(names[:15]) + ("…" if len(names) > 15 else ""),
                            {"items": names})
    except Exception as e:
        return _err(e)


@action("files_search", "Procura ficheiros pelo nome numa pasta permitida.",
        obj({"query": {"type": "string", "minLength": 1, "maxLength": 80}, "folder": _PATH}, ["query"]),
        risk=0, family="ficheiros", taints=True)
def files_search(ctx: Ctx, query: str, folder: str | None = None) -> ActionResult:
    try:
        bases = [_p(ctx, folder)] if folder else roots(ctx)
        q = query.lower()
        hits: list[str] = []
        scanned = 0
        for base in bases:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in ("node_modules", "appdata")]
                for fn in filenames:
                    scanned += 1
                    if q in fn.lower():
                        hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= 10 or scanned > 20000:
                        break
                if len(hits) >= 10 or scanned > 20000:
                    break
        if not hits:
            return ActionResult(True, f"Não encontrei nada com '{query}'.")
        return ActionResult(True, f"Encontrei {len(hits)}: " + "; ".join(Path(h).name for h in hits[:5]), {"paths": hits})
    except Exception as e:
        return _err(e)


@action("files_open", "Abre um ficheiro (documento, imagem, PDF…) com a app predefinida. Não abre executáveis.",
        obj({"path": _PATH}, ["path"]), risk=1, family="ficheiros", summarize=lambda a: f"abrir {a.get('path')}")
def files_open(ctx: Ctx, path: str) -> ActionResult:
    try:
        p = _p(ctx, path)
        if p.suffix.lower() in EXEC_EXT:
            return ActionResult(False, "Não abro executáveis nem scripts por segurança.")
        if IS_WIN:
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return ActionResult(True, f"A abrir {p.name}.")
    except Exception as e:
        return _err(e)


@action("files_read_text", "Lê um ficheiro de texto (até ~20 KB) para o resumir ou responder sobre ele.",
        obj({"path": _PATH}, ["path"]), risk=1, family="ficheiros", taints=True)
def files_read_text(ctx: Ctx, path: str) -> ActionResult:
    try:
        p = _p(ctx, path)
        if p.suffix.lower() not in TEXT_EXT:
            return ActionResult(False, "Só leio ficheiros de texto.")
        data = p.read_bytes()[:20000].decode("utf-8", errors="replace")
        return ActionResult(True, data, {"path": str(p)})
    except Exception as e:
        return _err(e)


@action("files_create_folder", "Cria uma pasta dentro de uma pasta permitida.", obj({"path": _PATH}, ["path"]),
        risk=2, family="ficheiros", summarize=lambda a: f"criar pasta {a.get('path')}")
def files_create_folder(ctx: Ctx, path: str) -> ActionResult:
    try:
        p = _p(ctx, path, must_exist=False)
        p.mkdir(parents=True, exist_ok=True)
        return ActionResult(True, f"Pasta {p.name} criada.")
    except Exception as e:
        return _err(e)


def _two(ctx: Ctx, src: str, dst: str) -> tuple[Path, Path]:
    s = _p(ctx, src)
    d = _p(ctx, dst, must_exist=False)
    if d.is_dir():
        d = d / s.name
    if d.exists():
        raise PathDenied("O destino já existe; não substituo ficheiros.")
    d.parent.mkdir(parents=True, exist_ok=True)
    return s, d


@action("files_move", "Move um ficheiro ou pasta (nunca substitui).",
        obj({"source": _PATH, "destination": _PATH}, ["source", "destination"]), risk=2, family="ficheiros",
        summarize=lambda a: f"mover {a.get('source')} → {a.get('destination')}")
def files_move(ctx: Ctx, source: str, destination: str) -> ActionResult:
    try:
        s, d = _two(ctx, source, destination)
        shutil.move(str(s), str(d))
        return ActionResult(True, f"Movido para {d.parent.name}.")
    except Exception as e:
        return _err(e)


@action("files_copy", "Copia um ficheiro ou pasta (nunca substitui).",
        obj({"source": _PATH, "destination": _PATH}, ["source", "destination"]), risk=2, family="ficheiros",
        summarize=lambda a: f"copiar {a.get('source')} → {a.get('destination')}")
def files_copy(ctx: Ctx, source: str, destination: str) -> ActionResult:
    try:
        s, d = _two(ctx, source, destination)
        shutil.copytree(s, d) if s.is_dir() else shutil.copy2(s, d)
        return ActionResult(True, "Copiado.")
    except Exception as e:
        return _err(e)


@action("files_rename", "Muda o nome a um ficheiro ou pasta.",
        obj({"path": _PATH, "new_name": {"type": "string", "minLength": 1, "maxLength": 120}}, ["path", "new_name"]),
        risk=2, family="ficheiros", summarize=lambda a: f"renomear {a.get('path')} → {a.get('new_name')}")
def files_rename(ctx: Ctx, path: str, new_name: str) -> ActionResult:
    try:
        p = _p(ctx, path)
        if any(c in new_name for c in '/\\:*?"<>|') or new_name in (".", ".."):
            return ActionResult(False, "Nome inválido.")
        d = p.with_name(new_name)
        resolve_inside(d, roots(ctx), must_exist=False)
        if d.exists():
            return ActionResult(False, "Já existe um ficheiro com esse nome.")
        p.rename(d)
        return ActionResult(True, "Renomeado.")
    except Exception as e:
        return _err(e)


@action("files_delete", "Envia um ficheiro ou pasta para a Reciclagem (recuperável).", obj({"path": _PATH}, ["path"]),
        risk=3, family="ficheiros", summarize=lambda a: f"ENVIAR PARA A RECICLAGEM: {a.get('path')}")
def files_delete(ctx: Ctx, path: str) -> ActionResult:
    try:
        p = _p(ctx, path)
        if p in roots(ctx):
            return ActionResult(False, "Não apago uma pasta-raiz permitida.")
        import send2trash
        send2trash.send2trash(str(p))
        return ActionResult(True, f"{p.name} foi para a Reciclagem.")
    except Exception as e:
        return _err(e)
