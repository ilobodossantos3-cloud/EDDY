"""Resolução segura de caminhos: bloqueia '..', links simbólicos para fora e pastas sensíveis."""
from __future__ import annotations

import os
from pathlib import Path


class PathDenied(PermissionError):
    pass


# Nomes de pastas/ficheiros que nunca são tocados, esteja onde estiver.
BLOCKED_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".env", ".git-credentials", ".netrc",
    "id_rsa", "id_ed25519", "known_hosts", "credentials", "credentials.json",
    "login data", "cookies", "web data", "keychain", "keepass", "bitwarden", "1password",
    "ntuser.dat", "sam", "system32", "syswow64", "windows", "appdata",
}
BLOCKED_SUFFIXES = {".kdbx", ".pem", ".key", ".pfx", ".p12", ".ppk"}


def _is_blocked(p: Path) -> bool:
    parts = [x.lower() for x in p.parts]
    if any(x in BLOCKED_NAMES for x in parts):
        return True
    return p.suffix.lower() in BLOCKED_SUFFIXES


def resolve_inside(path: str | os.PathLike, roots: list[Path], must_exist: bool = False) -> Path:
    """Resolve `path` e garante que fica dentro de uma das `roots`.

    Caminhos relativos são tentados em cada raiz. Segue links simbólicos antes de validar.
    """
    raw = os.path.expanduser(str(path))
    if "\x00" in raw:
        raise PathDenied("Caminho inválido.")
    real_roots = []
    for r in roots:
        try:
            real_roots.append(Path(r).expanduser().resolve())
        except OSError:
            continue
    if not real_roots:
        raise PathDenied("Não há pastas permitidas configuradas.")
    p = Path(raw)
    candidates = [p] if p.is_absolute() else [r / p for r in real_roots]
    last_err = "Caminho fora das pastas permitidas."
    for cand in candidates:
        try:
            rp = cand.resolve()
        except (OSError, RuntimeError):
            continue
        if _is_blocked(rp):
            last_err = "Esse caminho está bloqueado por segurança."
            continue
        for root in real_roots:
            try:
                rp.relative_to(root)
            except ValueError:
                continue
            if must_exist and not rp.exists():
                last_err = "Esse ficheiro ou pasta não existe."
                break
            return rp
    raise PathDenied(last_err)


def expand_roots(raw_roots: list[str]) -> list[Path]:
    out = []
    for r in raw_roots:
        p = Path(os.path.expanduser(r))
        if p.exists():
            out.append(p.resolve())
    return out
