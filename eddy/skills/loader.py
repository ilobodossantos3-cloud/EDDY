"""Habilidades: pastas com SKILL.md (frontmatter lido no arranque; corpo só quando é usada) e run.py opcional."""
from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

from ..vault.store import parse_frontmatter

_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]{1,40}$")


@dataclass
class SkillInfo:
    name: str
    description: str
    triggers: list[str]
    path: Path
    has_code: bool


class SkillManager:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._skills: dict[str, SkillInfo] = {}
        self.scan()

    def scan(self) -> None:
        self._skills = {}
        if not self.root.exists():
            return
        for d in sorted(self.root.iterdir()):
            md = d / "SKILL.md"
            if d.is_dir() and md.exists() and _NAME.match(d.name):
                meta, _ = parse_frontmatter(md.read_text(encoding="utf-8"))  # só frontmatter é usado aqui
                trig = [t.strip() for t in meta.get("triggers", "").split(",") if t.strip()]
                self._skills[d.name] = SkillInfo(d.name, meta.get("description", ""), trig, d, (d / "run.py").exists())

    def list(self) -> list[SkillInfo]:
        return list(self._skills.values())

    def get(self, name: str) -> SkillInfo | None:
        return self._skills.get(name)

    def guidance(self, name: str) -> str:
        info = self._skills[name]
        _, body = parse_frontmatter((info.path / "SKILL.md").read_text(encoding="utf-8"))
        return body.strip()

    def run(self, name: str, ctx, user_input: str = "") -> str:
        info = self._skills.get(name)
        if info is None:
            raise KeyError(f"Habilidade '{name}' não existe.")
        result = ""
        if info.has_code:
            spec = importlib.util.spec_from_file_location(f"eddy_skill_{name.replace('-', '_')}", info.path / "run.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            result = str(mod.run(ctx, user_input) or "")
        return f"{result}\n\n[Instruções da habilidade]\n{self.guidance(name)}".strip()
