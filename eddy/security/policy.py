"""Política de risco. Decide o que acontece a cada ação. NUNCA é influenciada pelo texto do modelo."""
from __future__ import annotations

from dataclasses import dataclass, field


class Verdict:
    ALLOW = "allow"          # executa já
    DELAY = "delay"          # avisa, espera um pouco (cancelável) e executa
    CONFIRM = "confirm"      # pede confirmação explícita
    DENY = "deny"            # recusa


@dataclass
class Session:
    """Estado de segurança da sessão."""
    tainted: bool = False                 # leu conteúdo externo nesta conversa
    approved: set[str] = field(default_factory=set)  # ações de nível 2 já aprovadas na sessão
    panic: bool = False                   # botão de pânico ativo
    mode: str = "normal"                  # normal | safe
    dry_run: bool = False

    def reset_taint(self) -> None:
        self.tainted = False


@dataclass
class Decision:
    verdict: str
    reason: str = ""


class PolicyEngine:
    def __init__(self, session: Session):
        self.session = session

    def evaluate(self, name: str, risk: int) -> Decision:
        s = self.session
        if risk not in (0, 1, 2, 3):
            return Decision(Verdict.DENY, "Nível de risco inválido.")
        if s.panic and risk >= 2:
            return Decision(Verdict.DENY, "Modo pânico ativo: ações de risco desligadas.")
        if s.mode == "safe" and risk >= 2:
            return Decision(Verdict.DENY, "Modo seguro: só são permitidas ações de nível 0 e 1.")
        if risk == 3:
            return Decision(Verdict.CONFIRM, "Ação de nível 3.")
        if risk == 2:
            if s.tainted:
                return Decision(Verdict.CONFIRM, "Li conteúdo externo nesta conversa; preciso de confirmação.")
            if name not in s.approved:
                return Decision(Verdict.CONFIRM, "Primeira vez nesta sessão.")
            return Decision(Verdict.DELAY, "Nível 2.")
        return Decision(Verdict.ALLOW, "")
