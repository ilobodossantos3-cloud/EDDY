"""Expõe as habilidades ao modelo."""
from __future__ import annotations

from .registry import ActionResult, Ctx, action, obj


@action("skills_list", "Lista as habilidades disponíveis e o que fazem.", obj(), risk=0, family="habilidades")
def skills_list(ctx: Ctx) -> ActionResult:
    if ctx.skills is None:
        return ActionResult(True, "Sem habilidades carregadas.")
    s = ctx.skills.list()
    return ActionResult(True, "; ".join(f"{i.name}: {i.description}" for i in s) or "Sem habilidades.")


@action("run_skill", "Executa uma habilidade pelo nome (ex.: metricas, caixa-de-entrada, tendencias, plano-de-hoje, vault).",
        obj({"name": {"type": "string", "pattern": r"^[a-z0-9\-]{2,40}$"}, "input": {"type": "string", "maxLength": 2000}},
            ["name"]), risk=1, taints=False, family="habilidades", summarize=lambda a: f"habilidade '{a.get('name')}'")
def run_skill(ctx: Ctx, name: str, input: str = "") -> ActionResult:
    if ctx.skills is None or ctx.skills.get(name) is None:
        return ActionResult(False, f"Não tenho a habilidade '{name}'.")
    try:
        return ActionResult(True, ctx.skills.run(name, ctx, input))
    except Exception as e:
        return ActionResult(False, f"A habilidade '{name}' falhou ({type(e).__name__}: {str(e)[:120]}).")
