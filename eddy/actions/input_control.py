"""Teclado, rato e área de transferência. Nível 2: afetam o que estás a fazer."""
from __future__ import annotations

import time

from .registry import ActionResult, Ctx, action, obj

_ALLOWED_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "ctrl", "alt", "shift", "win", "enter", "tab", "esc", "space", "backspace", "delete", "up", "down", "left",
    "right", "home", "end", "pageup", "pagedown", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12", "volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack"}
_BLOCKED_COMBOS = [{"ctrl", "alt", "delete"}, {"win", "r"}]  # nunca por voz: Executar / segurança do Windows


def _pg():
    import pyautogui  # type: ignore
    pyautogui.FAILSAFE = True   # rato no canto do ecrã = para tudo
    pyautogui.PAUSE = 0.05
    return pyautogui


@action("type_text", "Escreve texto onde estiver o cursor (suporta acentos).",
        obj({"text": {"type": "string", "minLength": 1, "maxLength": 1000}}, ["text"]), risk=2, family="teclado",
        summarize=lambda a: f"escrever {len(a.get('text', ''))} caracteres no cursor")
def type_text(ctx: Ctx, text: str) -> ActionResult:
    try:
        from pynput.keyboard import Controller  # type: ignore
        time.sleep(0.2)
        Controller().type(text)
        return ActionResult(True, "Escrito.")
    except ImportError:
        pass
    try:
        _pg().write(text, interval=0.01)
        return ActionResult(True, "Escrito (pode falhar com acentos; instala 'pynput').")
    except ImportError:
        return ActionResult(False, "Faltam 'pynput'/'pyautogui' (pip install -r requirements-control.txt).")
    except Exception as e:
        return ActionResult(False, f"Não consegui escrever ({type(e).__name__}).")


@action("press_keys", "Carrega numa combinação de teclas, ex.: 'ctrl+c', 'alt+tab', 'win+d'.",
        obj({"combo": {"type": "string", "pattern": r"^[a-z0-9]+(\+[a-z0-9]+){0,3}$", "maxLength": 40}}, ["combo"]),
        risk=2, family="teclado", summarize=lambda a: f"teclas {a.get('combo')}")
def press_keys(ctx: Ctx, combo: str) -> ActionResult:
    keys = combo.lower().split("+")
    if not all(k in _ALLOWED_KEYS for k in keys):
        return ActionResult(False, "Tecla não permitida.")
    if any(b <= set(keys) for b in _BLOCKED_COMBOS):
        return ActionResult(False, "Essa combinação está bloqueada por segurança.")
    try:
        _pg().hotkey(*keys)
        return ActionResult(True, "Feito.")
    except ImportError:
        return ActionResult(False, "Falta 'pyautogui' (pip install -r requirements-control.txt).")
    except Exception as e:
        return ActionResult(False, f"Não consegui ({type(e).__name__}).")


@action("click", "Clica numa posição do ecrã (x, y em píxeis).",
        obj({"x": {"type": "integer", "minimum": 0, "maximum": 10000},
             "y": {"type": "integer", "minimum": 0, "maximum": 10000}}, ["x", "y"]), risk=2, family="teclado",
        summarize=lambda a: f"clicar em ({a.get('x')}, {a.get('y')})")
def click(ctx: Ctx, x: int, y: int) -> ActionResult:
    try:
        _pg().click(x, y)
        return ActionResult(True, "Cliquei.")
    except ImportError:
        return ActionResult(False, "Falta 'pyautogui'.")
    except Exception as e:
        return ActionResult(False, f"Não consegui ({type(e).__name__}).")


def _clip_get() -> str:
    try:
        import pyperclip  # type: ignore
        return pyperclip.paste()
    except ImportError:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        try:
            return r.clipboard_get()
        finally:
            r.destroy()


def _clip_set(text: str) -> None:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
    except ImportError:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()


@action("clipboard_get", "Lê o texto da área de transferência (pode conter dados sensíveis).", obj(), risk=2,
        taints=True, family="teclado")
def clipboard_get(ctx: Ctx) -> ActionResult:
    try:
        return ActionResult(True, _clip_get()[:4000])
    except Exception as e:
        return ActionResult(False, f"Não consegui ler a área de transferência ({type(e).__name__}).")


@action("clipboard_set", "Põe texto na área de transferência.",
        obj({"text": {"type": "string", "minLength": 1, "maxLength": 4000}}, ["text"]), risk=2, family="teclado",
        summarize=lambda a: "copiar texto para a área de transferência")
def clipboard_set(ctx: Ctx, text: str) -> ActionResult:
    try:
        _clip_set(text)
        return ActionResult(True, "Copiado.")
    except Exception as e:
        return ActionResult(False, f"Não consegui ({type(e).__name__}).")
