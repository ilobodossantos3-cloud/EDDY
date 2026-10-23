"""Executor: validação → limite de ritmo → política → confirmação → execução → auditoria."""
from __future__ import annotations

import logging
import time
import threading
from collections import deque
from typing import Any

import jsonschema

from ..security.audit import AuditLog
from ..security.confirm import ConfirmManager
from ..security.policy import PolicyEngine, Session, Verdict
from .registry import REGISTRY, ActionResult, Ctx

log = logging.getLogger("eddy.exec")


class Executor:
    def __init__(self, ctx: Ctx, session: Session, audit: AuditLog, confirm: ConfirmManager):
        self.ctx = ctx
        self.session = session
        self.audit = audit
        self.confirm = confirm
        self.policy = PolicyEngine(session)
        self._times: deque[float] = deque()
        self._cancel = threading.Event()
        self.level2_delay = float(ctx.cfg.get("security.level2_delay_s", 1.0))
        self.max_per_min = int(ctx.cfg.get("security.max_actions_per_minute", 30))
        ctx.executor = self

    # -- pânico -------------------------------------------------------
    def panic(self) -> None:
        self.session.panic = True
        self._cancel.set()
        self.confirm.cancel_all()
        self.ctx.emit("panic", {})
        self.audit.write(event="panic")

    def clear_panic(self) -> None:
        self.session.panic = False
        self._cancel.clear()
        self.ctx.emit("panic_cleared", {})

    # -- catálogo ------------------------------------------------------
    def catalog(self) -> list[dict]:
        """Só ações permitidas no modo atual."""
        out = []
        for spec in REGISTRY.values():
            if self.session.mode == "safe" and spec.risk >= 2:
                continue
            if spec.name == "shell_run" and not self.ctx.cfg.get("security.shell.enabled", False):
                continue
            out.append(spec.tool_def())
        return out

    # -- ritmo ---------------------------------------------------------
    def _rate_ok(self) -> bool:
        now = time.time()
        while self._times and now - self._times[0] > 60:
            self._times.popleft()
        if len(self._times) >= self.max_per_min:
            return False
        self._times.append(now)
        return True

    # -- execução ------------------------------------------------------
    def execute(self, name: str, args: dict | None, origin: str = "llm", plan_approved: bool = False,
                request: str = "") -> ActionResult:
        args = dict(args or {})
        spec = REGISTRY.get(name)
        if spec is None:
            self.audit.write(event="action", action=name, outcome="desconhecida", origin=origin)
            return ActionResult(False, f"Não tenho a ação '{name}'.")
        if name == "shell_run" and not self.ctx.cfg.get("security.shell.enabled", False):
            return ActionResult(False, "O shell está desligado nas definições de segurança.")
        try:
            jsonschema.validate(args, spec.schema)
        except jsonschema.ValidationError as e:
            msg = e.message[:160]
            self.audit.write(event="action", action=name, args=args, outcome="args_invalidos", origin=origin)
            return ActionResult(False, f"Argumentos inválidos para {name}: {msg}")
        if not self._rate_ok():
            self.audit.write(event="action", action=name, args=args, outcome="limite_ritmo", origin=origin)
            return ActionResult(False, "Calma, estou a receber ações a mais por minuto. Abrandei por segurança.")

        decision = self.policy.evaluate(name, spec.risk)
        if decision.verdict == Verdict.DENY:
            self.audit.write(event="action", action=name, args=args, level=spec.risk, outcome="negada",
                             reason=decision.reason, origin=origin)
            return ActionResult(False, decision.reason)

        summary = spec.describe_call(args)
        confirmed_by = "-"
        if plan_approved and spec.risk == 2 and decision.verdict in (Verdict.CONFIRM, Verdict.DELAY):
            decision.verdict = Verdict.DELAY
            confirmed_by = "plano"
        if decision.verdict == Verdict.CONFIRM:
            self.ctx.emit("action_pending", {"action": name, "summary": summary, "level": spec.risk})
            if self.session.dry_run:
                self.audit.write(event="action", action=name, args=args, level=spec.risk, outcome="simulado", origin=origin)
                return ActionResult(True, f"[simulação] pediria confirmação para: {summary}")
            ok = self.confirm.request(name, args, summary, spec.risk)
            if not ok:
                self.audit.write(event="action", action=name, args=args, level=spec.risk, outcome="nao_confirmada",
                                 origin=origin)
                self.ctx.emit("action_cancelled", {"action": name, "summary": summary, "level": spec.risk, "ok": False})
                return ActionResult(False, "Não foi confirmado, por isso não fiz nada.")
            confirmed_by = "utilizador"
            if spec.risk == 2:
                self.session.approved.add(name)
        elif decision.verdict == Verdict.DELAY:
            self.ctx.emit("action_pending", {"action": name, "summary": summary, "level": spec.risk, "delay": self.level2_delay})
            if not self.session.dry_run and self._cancel.wait(self.level2_delay):
                self.audit.write(event="action", action=name, args=args, level=spec.risk, outcome="cancelada", origin=origin)
                self.ctx.emit("action_cancelled", {"action": name, "summary": summary, "level": spec.risk, "ok": False})
                return ActionResult(False, "Cancelado.")

        if self.session.panic and spec.risk >= 2:
            return ActionResult(False, "Modo pânico ativo.")

        if self.session.dry_run:
            self.audit.write(event="action", action=name, args=args, level=spec.risk, outcome="simulado", origin=origin)
            self.ctx.emit("action_done", {"action": name, "summary": summary, "level": spec.risk, "ok": True, "dry": True})
            return ActionResult(True, f"[simulação] faria: {summary}")

        t0 = time.time()
        try:
            res = spec.func(self.ctx, **args)
        except Exception as e:  # nunca deixar a exceção rebentar o Eddy
            log.exception("Erro na ação %s", name)
            res = ActionResult(False, f"A ação {name} falhou: {type(e).__name__}.")
        if spec.taints and res.ok:
            self.session.tainted = True
        self.audit.write(event="action", action=name, args=args, level=spec.risk, ok=res.ok,
                         confirmed_by=confirmed_by, origin=origin, ms=int((time.time() - t0) * 1000),
                         request=request, result=res.message[:200])
        self.ctx.emit("action_done", {"action": name, "summary": summary, "level": spec.risk, "ok": res.ok,
                                      "message": res.message[:200]})
        return res

    def confirm_plan(self, summary: str, level: int) -> bool:
        """Confirmação única para uma rotina inteira."""
        if self.session.dry_run:
            return True
        return self.confirm.request("routine_plan", {"plan": summary}, summary, level)
