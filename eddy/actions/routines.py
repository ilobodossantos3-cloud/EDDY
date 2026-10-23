"""Rotinas: sequências de ações em config/routines.yaml. O risco do plano é o máximo dos passos."""
from __future__ import annotations

import re

import yaml

from .registry import REGISTRY, ActionResult, Ctx, action, obj

_NAME = {"type": "string", "pattern": r"^[a-z0-9áàâãéêíóôõúç\- ]{2,40}$"}


def load_routines(ctx: Ctx) -> dict:
    try:
        return yaml.safe_load(ctx.cfg.path("config/routines.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "-", s.strip().lower())


def find_routine(ctx: Ctx, name: str):
    r = load_routines(ctx)
    n = _norm(name)
    for k, v in r.items():
        if _norm(k) == n:
            return k, v
    return None


@action("routines_list", "Lista as rotinas disponíveis.", obj(), risk=0, family="rotinas")
def routines_list(ctx: Ctx) -> ActionResult:
    r = load_routines(ctx)
    if not r:
        return ActionResult(True, "Ainda não tens rotinas.")
    return ActionResult(True, "Rotinas: " + "; ".join(f"{k} ({v.get('description', '')})" for k, v in r.items()))


@action("routine_run", "Executa uma rotina pelo nome.", obj({"name": _NAME}, ["name"]), risk=1, family="rotinas",
        summarize=lambda a: f"rotina '{a.get('name')}'")
def routine_run(ctx: Ctx, name: str) -> ActionResult:
    found = find_routine(ctx, name)
    if not found:
        return ActionResult(False, f"Não conheço a rotina '{name}'.")
    key, rt = found
    steps = rt.get("steps") or []
    unknown = [s.get("action") for s in steps if s.get("action") not in REGISTRY]
    if unknown:
        return ActionResult(False, f"A rotina usa ações que não existem: {', '.join(map(str, unknown))}.")
    risk = max((REGISTRY[s["action"]].risk for s in steps), default=0)
    plan_ok = False
    if risk >= 2:
        plan = "; ".join(REGISTRY[s["action"]].describe_call(s.get("args") or {}) for s in steps)
        if not ctx.executor.confirm_plan(f"Rotina '{key}': {plan}", risk):
            return ActionResult(False, "Rotina cancelada.")
        plan_ok = True
    done, fails = 0, []
    for s in steps:
        res = ctx.executor.execute(s["action"], s.get("args") or {}, origin=f"rotina:{key}", plan_approved=plan_ok)
        if res.ok:
            done += 1
        else:
            fails.append(f"{s['action']}: {res.message}")
            if ctx.session is not None and ctx.session.panic:
                break
    if fails:
        return ActionResult(False, f"Rotina '{key}': {done} passos feitos, falhou: {fails[0]}")
    return ActionResult(True, f"Rotina '{key}' concluída ({done} passos).")


@action("routine_save", "Guarda uma nova rotina (passos = lista de {action, args}). Pede confirmação.",
        obj({"name": _NAME, "description": {"type": "string", "maxLength": 200},
             "steps": {"type": "array", "minItems": 1, "maxItems": 12, "items": obj(
                 {"action": {"type": "string"}, "args": {"type": "object"}}, ["action"])}},
            ["name", "steps"]), risk=3, family="rotinas",
        summarize=lambda a: f"GUARDAR rotina '{a.get('name')}' com {len(a.get('steps', []))} passos: "
                            + ", ".join(s.get('action', '?') for s in a.get('steps', [])))
def routine_save(ctx: Ctx, name: str, steps: list, description: str = "") -> ActionResult:
    bad = [s["action"] for s in steps if s["action"] not in REGISTRY or s["action"] in ("routine_save", "shell_run", "power")]
    if bad:
        return ActionResult(False, f"Ações não permitidas numa rotina: {', '.join(bad)}.")
    path = ctx.cfg.path("config/routines.yaml")
    data = load_routines(ctx)
    data[_norm(name)] = {"description": description, "steps": steps}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ActionResult(True, f"Rotina '{name}' guardada.")
