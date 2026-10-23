"""Shell restrito: DESLIGADO por omissão. Só comandos exatos da allowlist, sem shell=True, nível 3."""
from __future__ import annotations

import shlex
import subprocess

from ..security.sanitize import redact
from .registry import ActionResult, Ctx, action, obj


def _norm(cmd: str) -> str:
    return " ".join(cmd.split())


@action("shell_run", "Executa um comando da allowlist de segurança (security.shell.allowed_commands).",
        obj({"command": {"type": "string", "minLength": 1, "maxLength": 200}}, ["command"]), risk=3, taints=True,
        family="avançado", summarize=lambda a: f"EXECUTAR COMANDO: {a.get('command')}")
def shell_run(ctx: Ctx, command: str) -> ActionResult:
    if not ctx.cfg.get("security.shell.enabled", False):
        return ActionResult(False, "O shell está desligado.")
    allowed = {_norm(c) for c in ctx.cfg.get("security.shell.allowed_commands", []) or []}
    if _norm(command) not in allowed:
        return ActionResult(False, "Esse comando não está na allowlist.")
    try:
        r = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=20, cwd=str(ctx.cfg.root),
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ActionResult(False, "O comando demorou demais e foi cortado.")
    except FileNotFoundError:
        return ActionResult(False, "Comando não encontrado.")
    out = redact((r.stdout or r.stderr or "").strip())[:1500]
    return ActionResult(r.returncode == 0, out or f"Terminou com código {r.returncode}.")
