import shutil
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eddy.config import Config  # noqa: E402
from eddy.llm.base import LLMResponse, ToolCall  # noqa: E402


class FakeProvider:
    """Modelo falso com respostas em guião."""
    def __init__(self, script, supports_tools=True, name="fake", is_cloud=False, vision=False):
        self.script, self.supports_tools, self.name, self.is_cloud, self.vision = list(script), supports_tools, name, is_cloud, vision
        self.calls = []
        self.model = "fake-model"

    def chat(self, messages, tools=None, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        item = self.script.pop(0) if self.script else "ok"
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(text=item)


class FakeLLM:
    def __init__(self, provider):
        self._p = provider
        self.active = "fake"
        self.using_fallback = False

    @property
    def provider(self):
        return self._p

    def get(self, name=None):
        return self._p

    def chat(self, messages, tools=None, **kw):
        return self._p.chat(messages, tools, **kw), self._p

    def profiles(self):
        return ["fake"]

    def switch(self, name):
        return self._p

    def is_cloud(self):
        return self._p.is_cloud


def tc(name, **args):
    return LLMResponse(tool_calls=[ToolCall(id="c1", name=name, arguments=args)])


@pytest.fixture
def tmp_cfg(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "apps.yaml").write_text(
        "apps:\n  chrome: {exe: 'chrome.exe', aliases: ['google chrome']}\n  calculadora: {exe: 'calc.exe', aliases: []}\n", encoding="utf-8")
    (tmp_path / "config" / "routines.yaml").write_text(
        "teste:\n  description: t\n  steps:\n    - {action: time_now, args: {}}\n", encoding="utf-8")
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    docs = tmp_path / "Documents"
    docs.mkdir()
    data = {
        "user": {"name": "Santos", "timezone": "Europe/Lisbon"},
        "personality": {"sarcasm": 2},
        "llm": {"active": "fake", "profiles": {"fake": {"type": "openai_compat", "base_url": "http://localhost:1/v1", "model": "m"}}},
        "voice": {"enabled": False, "tts": {"order": ["fish", "piper"], "private_mode": False, "max_chars": 500,
                                              "cache_dir": "cache/tts", "fish": {"model": "s2.1-pro", "reference_id": "voz1", "format": "pcm",
                                                                                "sample_rate": 44100, "daily_char_limit": 1000}}},
        "vault": {"path": "vault", "context_notes": 3, "context_chars": 500},
        "security": {"mode": "normal", "dry_run": False, "confirm_timeout_s": 2, "level2_delay_s": 0.0,
                     "max_actions_per_minute": 100, "max_steps_per_task": 6, "allowed_folders": [str(docs)],
                     "shell": {"enabled": False, "allowed_commands": ["git status"]}},
        "plugins": {"enabled": []}, "skills": {"dir": "skills"}, "inbox": {"rss": []},
        "scheduler": {"enabled": False},
    }
    return Config(data, tmp_path)


@pytest.fixture
def make_eddy(tmp_cfg):
    from eddy.app import Eddy

    def _make(provider=None, **kw):
        llm = FakeLLM(provider or FakeProvider([]))
        e = Eddy(tmp_cfg, voice=False, llm=llm, **kw)
        return e
    return _make


def auto_confirm(eddy, accept=True, delay=0.0):
    """Simula o utilizador a carregar no botão do HUD."""
    def hook(kind, data):
        if kind == "confirm_request":
            threading.Timer(delay, lambda: eddy.confirm.resolve(data["id"], accept, source="hud")).start()
    eddy.subscribe(hook)
