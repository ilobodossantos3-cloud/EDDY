"""Redação de segredos, delimitação de conteúdo não confiável e proteção SSRF."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

_SECRET_PATTERNS = [
    (re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_\-]{16,}\b"), "[CHAVE]"),
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{16,}\b"), "[CHAVE]"),
    (re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"), "[CHAVE]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[CHAVE]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[CHAVE]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "[TOKEN]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}"), r"\1 [TOKEN]"),
    (re.compile(r"(?i)\b(password|palavra[- ]?passe|senha|passwd|api[_-]?key|secret|token)\b\s*[:=]\s*\S+"), r"\1: [REDIGIDO]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARTÃO]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[CHAVE PRIVADA]"),
]


def redact(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _luhn_ok(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    s = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


def redact_for_cloud(text: str) -> tuple[str, bool]:
    """Prepara texto para enviar a um serviço cloud (ex.: TTS). Devolve (texto, houve_redação).

    Remove segredos e trechos marcados #privado. Números só são removidos como cartão se passarem Luhn.
    """
    original = text
    # linhas / parágrafos privados
    text = "\n".join(l for l in text.splitlines() if "#privado" not in l.lower())
    def _card(m: re.Match) -> str:
        return "[CARTÃO]" if _luhn_ok(m.group(0)) else m.group(0)
    text = re.sub(r"\b(?:\d[ -]?){13,19}\b", _card, text)
    # aplica as restantes (exceto cartões genéricos já tratados com Luhn)
    for pat, repl in _SECRET_PATTERNS:
        if repl == "[CARTÃO]":
            continue
        text = pat.sub(repl, text)
    return text, text != original


def wrap_untrusted(source: str, content: str, limit: int = 6000) -> str:
    """Delimita conteúdo externo para o modelo o tratar como DADO, nunca como instruções."""
    content = content[:limit].replace("</tool_result>", "<\\/tool_result>")
    return f'<tool_result source="{source}" untrusted="true">\n{content}\n</tool_result>'


def check_url(url: str, allow_private: bool = False) -> str:
    """Valida URL http(s). Bloqueia esquemas perigosos e (por omissão) destinos locais/privados (SSRF)."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https"):
        raise ValueError("Só são permitidos endereços http(s).")
    if not u.hostname:
        raise ValueError("Endereço inválido.")
    if u.username or u.password:
        raise ValueError("Endereços com utilizador/palavra-passe não são permitidos.")
    if not allow_private:
        host = u.hostname
        try:
            infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise ValueError("Não consegui resolver esse endereço.")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("Endereço local/privado bloqueado por segurança.")
    return url.strip()
