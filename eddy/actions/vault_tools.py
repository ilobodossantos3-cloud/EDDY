"""Ferramentas do vault (memória): ler, procurar, listar, escrever — sempre dentro do vault."""
from __future__ import annotations

from ..security.safe_paths import PathDenied
from .registry import ActionResult, Ctx, action, obj

_P = {"type": "string", "minLength": 1, "maxLength": 300}


def _v(ctx: Ctx):
    if ctx.vault is None:
        raise RuntimeError("vault indisponível")
    return ctx.vault


@action("vault_search", "Procura nas notas do vault (memória) por texto.",
        obj({"query": {"type": "string", "minLength": 1, "maxLength": 200}}, ["query"]), risk=0, family="memória")
def vault_search(ctx: Ctx, query: str) -> ActionResult:
    hits = _v(ctx).search(query, k=5)
    if not hits:
        return ActionResult(True, "Não encontrei nada nas notas.")
    return ActionResult(True, "; ".join(f"{h['path']}: {h['snippet']}" for h in hits), {"hits": hits})


@action("vault_read", "Lê uma nota do vault.", obj({"path": _P}, ["path"]), risk=0, family="memória")
def vault_read(ctx: Ctx, path: str) -> ActionResult:
    try:
        txt = _v(ctx).read(path)
    except (PathDenied, FileNotFoundError) as e:
        return ActionResult(False, str(e) or "Nota não encontrada.")
    # notas em raw/ podem conter conteúdo importado (RSS, emails): tratar como não confiável
    ctx.session.tainted = ctx.session.tainted or path.replace("\\", "/").lstrip("/").startswith("raw/")
    return ActionResult(True, txt[:6000])


@action("vault_list", "Lista notas de uma pasta do vault (raw, wiki, outputs).",
        obj({"folder": {"type": "string", "maxLength": 100}}, []), risk=0, family="memória")
def vault_list(ctx: Ctx, folder: str = "") -> ActionResult:
    try:
        items = _v(ctx).list(folder)
    except PathDenied as e:
        return ActionResult(False, str(e))
    return ActionResult(True, f"{len(items)} notas: " + ", ".join(items[:15]), {"items": items})


@action("vault_write", "Escreve ou acrescenta numa nota do vault (modo 'append' ou 'overwrite').",
        obj({"path": _P, "content": {"type": "string", "maxLength": 20000},
             "mode": {"type": "string", "enum": ["append", "overwrite"]}}, ["path", "content"]),
        risk=1, family="memória", summarize=lambda a: f"escrever na nota {a.get('path')}")
def vault_write(ctx: Ctx, path: str, content: str, mode: str = "append") -> ActionResult:
    try:
        _v(ctx).write(path, content, mode=mode)
    except PathDenied as e:
        return ActionResult(False, str(e))
    return ActionResult(True, "Guardado no vault.")
