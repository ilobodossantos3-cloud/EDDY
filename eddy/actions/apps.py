"""Aplicações: só as que estão na allowlist config/apps.yaml."""
from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from .registry import ActionResult, Ctx, action, obj

IS_WIN = sys.platform.startswith("win")
_APP_NAME = {"type": "string", "minLength": 1, "maxLength": 80}


def load_apps(ctx: Ctx) -> dict[str, dict]:
    path = ctx.cfg.path("config/apps.yaml")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    return {str(k).lower(): v for k, v in (data.get("apps") or {}).items() if isinstance(v, dict)}


def resolve_app(ctx: Ctx, name: str) -> tuple[str, dict] | None:
    apps = load_apps(ctx)
    n = name.strip().lower()
    index: dict[str, str] = {}
    for key, v in apps.items():
        index[key] = key
        for a in v.get("aliases") or []:
            index[str(a).lower()] = key
    if n in index:
        k = index[n]
        return k, apps[k]
    close = difflib.get_close_matches(n, list(index), n=1, cutoff=0.8)
    if close:
        k = index[close[0]]
        return k, apps[k]
    return None


def _launch(exe: str) -> None:
    if ":" in exe and not os.path.isabs(exe) and "\\" not in exe and "/" not in exe:  # URI (ms-settings:)
        if IS_WIN:
            os.startfile(exe)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", exe])
        return
    path = shutil.which(exe) or exe
    if IS_WIN:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    subprocess.Popen([path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@action("apps_list", "Lista as aplicações que posso abrir.", obj(), risk=0, family="apps")
def apps_list(ctx: Ctx) -> ActionResult:
    names = sorted(load_apps(ctx))
    return ActionResult(True, "Posso abrir: " + ", ".join(names) + "." if names else "Não há apps no registo.")


@action("app_open", "Abre uma aplicação do registo pelo nome (ex.: chrome, spotify, calculadora).",
        obj({"name": _APP_NAME}, ["name"]), risk=1, family="apps", summarize=lambda a: f"abrir {a.get('name')}")
def app_open(ctx: Ctx, name: str) -> ActionResult:
    found = resolve_app(ctx, name)
    if not found:
        return ActionResult(False, f"'{name}' não está no registo de apps. Adiciona-a a config/apps.yaml.")
    key, info = found
    try:
        _launch(str(info.get("exe", "")))
    except Exception as e:
        return ActionResult(False, f"Não consegui abrir {key} ({type(e).__name__}).")
    return ActionResult(True, f"A abrir {key}.")


@action("app_close", "Fecha uma aplicação do registo (pedido normal de fecho, sem forçar).",
        obj({"name": _APP_NAME}, ["name"]), risk=2, family="apps", summarize=lambda a: f"fechar {a.get('name')}")
def app_close(ctx: Ctx, name: str) -> ActionResult:
    found = resolve_app(ctx, name)
    if not found:
        return ActionResult(False, f"'{name}' não está no registo de apps.")
    key, info = found
    exe = Path(str(info.get("exe", ""))).name
    if not exe or ":" in exe:
        return ActionResult(False, f"Não sei fechar {key}.")
    if IS_WIN:
        r = subprocess.run(["taskkill", "/IM", exe], capture_output=True, text=True)  # sem /F: fecho gracioso
        ok = r.returncode == 0
    else:
        import psutil
        ok = False
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() == exe.lower():
                try:
                    p.terminate()
                    ok = True
                except Exception:
                    pass
    return ActionResult(ok, f"Pedi a {key} para fechar." if ok else f"{key} não parece estar aberto.")


@action("app_focus", "Traz uma janela para a frente pelo título ou nome da app.",
        obj({"name": _APP_NAME}, ["name"]), risk=1, family="apps", summarize=lambda a: f"focar {a.get('name')}")
def app_focus(ctx: Ctx, name: str) -> ActionResult:
    try:
        import pygetwindow as gw  # type: ignore
    except ImportError:
        return ActionResult(False, "Falta o pacote 'pygetwindow' (só Windows).")
    wins = [w for w in gw.getAllWindows() if name.lower() in (w.title or "").lower()]
    if not wins:
        return ActionResult(False, f"Não encontrei nenhuma janela com '{name}'.")
    try:
        w = wins[0]
        if w.isMinimized:
            w.restore()
        w.activate()
    except Exception as e:
        return ActionResult(False, f"Não consegui focar a janela ({type(e).__name__}).")
    return ActionResult(True, "Já está à frente.")
