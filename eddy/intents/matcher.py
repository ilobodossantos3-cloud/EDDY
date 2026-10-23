"""Matcher local de intenções em pt-PT: comandos simples e inequívocos executam-se sem chamar o LLM."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w%:\s\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_UNITS = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
          "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
          "quinze": 15, "dezasseis": 16, "dezassete": 17, "dezoito": 18, "dezanove": 19}
_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
         "noventa": 90}


def pt_number(text: str) -> int | None:
    """'30', 'trinta', 'vinte e cinco', 'cem' → int."""
    t = norm(text)
    m = re.search(r"\b(\d{1,3})\b", t)
    if m:
        return int(m.group(1))
    if re.search(r"\bcem\b", t):
        return 100
    words = t.split()
    for i, w in enumerate(words):
        if w in _TENS:
            n = _TENS[w]
            if i + 2 < len(words) and words[i + 1] == "e" and words[i + 2] in _UNITS:
                n += _UNITS[words[i + 2]]
            return n
        if w in _UNITS:
            return _UNITS[w]
    if "meia hora" in t:
        return 30
    return None


@dataclass
class Intent:
    kind: str                       # "action" | "special"
    name: str                       # nome da ação ou do comando especial
    args: dict
    speak_result: bool = False      # dizer a mensagem do resultado (hora, estado...) em vez de "Feito."


_ART = r"(?:o |a |os |as |um |uma )?"


def orig_tail(text: str, norm_tail: str) -> str:
    """Recupera o fim de `text` com acentos, dado o fim já normalizado (mesma tokenização)."""
    toks = re.sub(r"[^\w%:\s\-]", " ", text.lower()).split()
    n = len(norm_tail.split())
    return " ".join(toks[-n:]) if n else norm_tail


class IntentMatcher:
    def __init__(self, resolve_app: Callable[[str], str | None] | None = None):
        self.resolve_app = resolve_app or (lambda n: n)

    def match(self, text: str) -> Intent | None:
        t = norm(text)
        if not t:
            return None

        # ---- comandos especiais ----
        if re.search(r"\b(para tudo|pare tudo|cancela tudo|stop eddy|eddy para)\b", t):
            return Intent("special", "panic", {})
        if re.search(r"\b(retoma|reativa|desativa o panico|tira o panico)\b.*\b(acoes|tudo|panico)\b", t):
            return Intent("special", "clear_panic", {})
        if re.search(r"\bmodo privado\b", t):
            off = re.search(r"\b(desliga|desativa|sai|tira|para)\b", t)
            return Intent("special", "private_off" if off else "private_on", {})
        m = re.search(r"\b(muda|passa|troca|usa)\b.*\b(modelo|cerebro)\b\s*(?:para |a )?(?:o |a )?(\w[\w\-]*)?", t)
        if m and ("local" in t or "api" in t or m.group(3)):
            target = "local" if "local" in t else ("api" if "api" in t else m.group(3))
            return Intent("special", "switch_model", {"target": target})
        if re.search(r"\bmenos sarcasmo\b", t):
            return Intent("special", "sarcasm", {"delta": -1})
        if re.search(r"\bmais sarcasmo\b", t):
            return Intent("special", "sarcasm", {"delta": +1})
        m = re.search(r"\bsarcasmo (?:a |em |para |nivel )?(\w+)", t)
        if m and pt_number(m.group(1)) is not None and pt_number(m.group(1)) <= 3:
            return Intent("special", "sarcasm", {"level": pt_number(m.group(1))})
        if re.search(r"\bo que (fizeste|fez) (hoje|ontem)\b|\bhistorico de acoes\b", t):
            return Intent("special", "audit_summary", {})
        if re.search(r"\b(briefing|resumo do dia|como vai ser o dia|o que tenho (para )?hoje|poe me a par)\b", t):
            return Intent("special", "briefing", {})
        if re.search(r"\bo que (sabes|consegues) fazer\b|\bque acoes tens\b", t):
            return Intent("special", "help", {})

        # ---- som ----
        m = re.search(r"\bvolume\b.*?\b(?:a|para|em|nos)\b\s*(.+?)\s*(?:por cento|%)?$", t)
        if m:
            n = pt_number(m.group(1))
            if n is not None and 0 <= n <= 100:
                return Intent("action", "volume_set", {"percent": n})
        if re.search(r"\b(mais alto|aumenta o volume|sobe o volume|volume (mais )?(alto|acima))\b", t):
            return Intent("action", "volume_change", {"delta": 10})
        if re.search(r"\b(mais baixo|baixa o volume|diminui o volume|desce o volume|volume (mais )?(baixo|abaixo))\b", t):
            return Intent("action", "volume_change", {"delta": -10})
        if re.search(r"\b(silencio|silencia|muda o som|mute|cala o som)\b", t):
            return Intent("action", "media_key", {"key": "mute"})
        if re.search(r"\b(qual (e )?o volume|que volume)\b", t):
            return Intent("action", "volume_get", {}, True)
        if re.search(r"\b(pausa|poe em pausa|para a musica|retoma|continua a musica|play|da play)\b", t):
            return Intent("action", "media_key", {"key": "playpause"})
        if re.search(r"\b(proxima|seguinte|salta)\b( musica| faixa| a musica)?", t) and "pagina" not in t:
            return Intent("action", "media_key", {"key": "next"})
        if re.search(r"\b(musica anterior|faixa anterior|volta a musica|anterior)\b", t) and "dia" not in t:
            return Intent("action", "media_key", {"key": "previous"})

        # ---- sistema ----
        if re.search(r"\bque horas sao\b|\bque dia e hoje\b|\bqual e a data\b|\bem que dia estamos\b|\bdiz[- ]me as horas\b", t):
            return Intent("action", "time_now", {}, True)
        if re.search(r"\b(estado do (pc|sistema|computador)|como esta o (pc|computador)|quanta (ram|memoria))\b", t):
            return Intent("action", "system_status", {}, True)
        if re.search(r"\bbloqueia\b.*\b(pc|ecra|computador|sessao)\b|\bbloquear (o )?(pc|ecra|computador)\b", t):
            return Intent("action", "lock_screen", {})
        if re.search(r"\bcancela o (desligar|reiniciar)\b", t):
            return Intent("action", "power_cancel", {})
        if re.search(r"\b(desliga|desligar) o (pc|computador)\b", t):
            return Intent("action", "power", {"mode": "shutdown"})
        if re.search(r"\b(reinicia|reiniciar) o (pc|computador)\b", t):
            return Intent("action", "power", {"mode": "restart"})
        if re.search(r"\b(que )?lembretes (tenho|tens)\b|\bquais sao os meus lembretes\b", t):
            return Intent("action", "reminders_list", {}, True)

        # ---- lembretes ----
        m = re.search(r"\b(?:lembra[- ]?me|avisa[- ]?me|poe um lembrete|cria um lembrete)\b\s*(?:de |para |que )?(.*)", t)
        if m:
            rest = m.group(1)
            mm = re.search(r"(?:daqui a|dentro de|em)\s+(.+?)\s+(minutos?|horas?)\b\s*(?:de |para |que )?(.*)", rest)
            if mm:
                n = pt_number(mm.group(1))
                if n:
                    mins = n * (60 if mm.group(2).startswith("hora") else 1)
                    return Intent("action", "remind", {"in_minutes": mins, "text": orig_tail(text, (mm.group(3) or "").strip()) or "lembrete"})
            mm = re.search(r"\bas\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|horas)?\b\s*(?:de |para |que )?(.*)", rest)
            if mm:
                hh, mi = int(mm.group(1)), int(mm.group(2) or 0)
                if 0 <= hh < 24 and 0 <= mi < 60:
                    return Intent("action", "remind", {"at": f"{hh}:{mi:02d}", "text": orig_tail(text, (mm.group(3) or "").strip()) or "lembrete"})

        # ---- web ----
        m = re.search(r"\b(?:pesquisa|procura|googla)\b\s*(?:no google |na web |online |na internet )?(?:por |sobre )?(.+)$", t)
        if m and len(m.group(1)) > 2 and not re.search(r"\b(ficheiro|ficheiros|nas notas|no vault|no pc)\b", t):
            return Intent("action", "web_search", {"query": orig_tail(text, m.group(1).strip())})

        # ---- apps ----
        m = re.search(rf"\b(?:abre|abrir|inicia|iniciar|lanca|lancar|arranca|abra)\b\s+{_ART}(.+)$", t)
        if m:
            app = self.resolve_app(m.group(1).strip())
            if app:
                return Intent("action", "app_open", {"name": app})
        m = re.search(rf"\b(?:fecha|fechar|encerra|encerrar|feche)\b\s+{_ART}(.+)$", t)
        if m:
            app = self.resolve_app(m.group(1).strip())
            if app:
                return Intent("action", "app_close", {"name": app})
        m = re.search(rf"\b(?:poe|mostra|traz)\b\s+{_ART}(.+?)\s+(?:a frente|em primeiro plano)$", t)
        if m:
            app = self.resolve_app(m.group(1).strip())
            if app:
                return Intent("action", "app_focus", {"name": app})
        return None
