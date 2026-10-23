"""Núcleo do Eddy: junta modelos, segurança, ações, voz e eventos para o HUD."""
from __future__ import annotations

import collections
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .actions import Ctx, Executor, load_builtin_actions
from .actions.registry import REGISTRY, load_plugins
from .config import Config
from .engine import lines
from .engine.agent import Agent
from .intents import Intent, IntentMatcher
from .llm import LLMManager
from .briefing import Briefing
from .reminders import Reminders
from .security.audit import AuditLog
from .security.confirm import ConfirmManager
from .security.killswitch import KillSwitch
from .security.policy import Session
from .skills import SkillManager
from .vault import VaultStore

log = logging.getLogger("eddy")

_HALLUCINATIONS = {"obrigado", "obrigada", "obrigado.", "legendas pela comunidade amara.org", "tchau", "ate ja",
                   "a seguir", "ate a proxima"}


class Eddy:
    def __init__(self, cfg: Config, *, voice: bool | None = None, safe: bool = False, dry_run: bool = False,
                 llm: LLMManager | None = None, tts: Any = None, stt: Any = None, recorder: Any = None):
        self.cfg = cfg
        load_builtin_actions()
        self._subs: list[Callable[[str, dict], None]] = []
        self._subs_lock = threading.Lock()
        self.events: collections.deque = collections.deque(maxlen=60)
        self.state = "idle"
        self.history: list[dict] = []
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._cancel_listen = threading.Event()
        self._pending_notice = ""
        self.started = time.time()

        # memória e habilidades
        self.vault = VaultStore(cfg.path(cfg.get("vault.path", "vault")))
        self.skills = SkillManager(cfg.path(cfg.get("skills.dir", "skills")))

        # segurança
        self.session = Session(mode="safe" if safe or cfg.get("security.mode") == "safe" else "normal",
                               dry_run=dry_run or bool(cfg.get("security.dry_run", False)))
        self.audit = AuditLog(cfg.path("logs/audit.jsonl"))
        self.confirm = ConfirmManager(float(cfg.get("security.confirm_timeout_s", 30)), self.emit)
        self.reminders = Reminders(cfg.path("logs/reminders.json"), self._on_reminder)
        self.ctx = Ctx(cfg=cfg, vault=self.vault, emit=self.emit, reminders=self.reminders, skills=self.skills,
                       session=self.session)
        self.executor = Executor(self.ctx, self.session, self.audit, self.confirm)
        self.briefing = Briefing(cfg)
        self.ctx.extras.update({"briefing": self.briefing, "eddy": self})
        for name in load_plugins(cfg):
            log.info("Plugin carregado: %s", name)

        # modelo
        self.llm = llm or LLMManager(cfg, on_fallback=self._on_llm_fallback)
        self.ctx.llm = self.llm
        self.agent = Agent(cfg, self.llm, self.executor, self.vault)
        self.matcher = IntentMatcher(self._resolve_app_name)

        # voz
        self.voice_enabled = bool(cfg.get("voice.enabled", True)) if voice is None else bool(voice)
        self.tts = tts
        self.stt = stt
        self.recorder = recorder
        if self.voice_enabled and tts is None and stt is None and recorder is None:
            self._init_voice()
        self.killswitch = KillSwitch(cfg.get("security.panic_hotkey", "ctrl+alt+esc"), self.panic)

    # ---------------------------------------------------------------- eventos
    def subscribe(self, fn: Callable[[str, dict], None]) -> None:
        with self._subs_lock:
            self._subs.append(fn)

    def unsubscribe(self, fn: Callable[[str, dict], None]) -> None:
        with self._subs_lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def emit(self, type_: str, data: dict | None = None) -> None:
        data = data or {}
        if type_ not in ("audio_level", "tick"):
            self.events.append({"type": type_, "data": data, "ts": time.time()})
        with self._subs_lock:
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(type_, data)
            except Exception:
                log.debug("subscritor falhou", exc_info=True)

    def set_state(self, s: str) -> None:
        if s != self.state:
            self.state = s
            self.emit("state", {"state": s})

    # ---------------------------------------------------------------- voz
    def _init_voice(self) -> None:
        from .voice.audio import AudioOut
        from .voice.stt import STT, Recorder
        from .voice.tts import TTSRouter
        audio = AudioOut(on_level=lambda v: self.emit("audio_level", {"level": v, "src": "out"}))
        self.tts = TTSRouter(self.cfg, audio, notify=self._on_voice_notice)
        self.stt = STT(self.cfg)
        self.recorder = Recorder(self.cfg, on_level=lambda v: self.emit("audio_level", {"level": v, "src": "in"}))

    def _on_voice_notice(self, kind: str, data: dict) -> None:
        self.emit(kind, data)
        if kind == "voice_fallback" and not self._pending_notice:
            self._pending_notice = lines.pick("voice_fallback", self._sarcasm())

    def _sarcasm(self) -> int:
        return int(self.cfg.get("personality.sarcasm", 2))

    def say(self, text: str, cache: bool = False) -> None:
        """Mostra a legenda e fala (se a voz estiver ativa)."""
        if not text:
            return
        self.emit("reply", {"text": text})
        if self.tts is not None and self.voice_enabled:
            self.set_state("speaking")
            try:
                self.tts.speak(text, cache=cache)
            finally:
                self.set_state("idle")
            if self._pending_notice:
                note, self._pending_notice = self._pending_notice, ""
                self.emit("reply", {"text": note})
                if self.tts is not None:
                    self.set_state("speaking")
                    try:
                        self.tts.speak(note, cache=False)
                    finally:
                        self.set_state("idle")

    # ---------------------------------------------------------------- push-to-talk
    def ptt_down(self) -> None:
        if not (self.voice_enabled and self.recorder):
            self.emit("voice_error", {"message": "A voz está desligada ou não instalada."})
            return
        self._cancel_listen.set()          # interrompe escuta de seguimento
        if self.tts is not None:
            self.tts.stop()                # barge-in
        try:
            self.recorder.start()
            self.set_state("listening")
        except Exception as e:
            self.emit("voice_error", {"message": f"Microfone indisponível: {str(e)[:120]}"})

    def ptt_up(self) -> None:
        if not (self.voice_enabled and self.recorder):
            return
        audio = self.recorder.stop()
        threading.Thread(target=self._process_audio, args=(audio,), daemon=True, name="eddy-voice").start()

    def _transcribe(self, audio) -> str:
        if self.tts is not None and getattr(self.tts, "private", False):
            self.emit("voice_error", {"message": "Modo privado: a voz está desligada (o áudio iria para a cloud). Escreve o pedido."})
            return ""
        self.set_state("thinking")
        try:
            text = self.stt.transcribe(audio)
        except Exception as e:
            self.emit("voice_error", {"message": f"Não consegui perceber o áudio: {str(e)[:120]}"})
            return ""
        t = re.sub(r"[^\w\s.]", "", text.lower()).strip()
        if t in _HALLUCINATIONS or len(t) < 2:
            return ""
        return text

    def _process_audio(self, audio) -> None:
        self._cancel_listen.clear()
        text = self._transcribe(audio)
        if not text:
            self.set_state("idle")
            return
        self.handle_text(text, source="voice")
        self._followup_loop()

    def _followup_loop(self) -> None:
        wait = float(self.cfg.get("voice.conversation.followup_seconds", 8))
        if wait <= 0 or not self.recorder:
            return
        while not self._cancel_listen.is_set() and not self.session.panic:
            self.set_state("listening")
            try:
                audio = self.recorder.listen_followup(wait, cancel=self._cancel_listen)
            except Exception:
                break
            if audio is None:
                break
            text = self._transcribe(audio)
            if not text:
                break
            self.handle_text(text, source="voice")
        self.set_state("idle")

    # ---------------------------------------------------------------- pedidos
    def handle_text(self, text: str, source: str = "text", speak: bool = True) -> str:
        """Processa um pedido (voz ou texto). Devolve a resposta falada."""
        text = (text or "").strip()
        if not text:
            return ""
        self.emit("transcript", {"text": text, "source": source})
        # confirmação por voz de uma ação pendente
        if self.confirm.pending():
            if not self.confirm.resolve_voice(text):
                self.emit("notice", {"text": "Há uma confirmação pendente: carrega em CONFIRMAR no HUD ou diz «confirma <código>»."})
            return ""
        with self._lock:
            now = time.time()
            if now - self._last_request > 120:      # nova conversa: esquece a contaminação anterior
                self.session.reset_taint()
            self._last_request = now
            self.set_state("thinking")
            try:
                reply, record = self._dispatch(text, source)
            except Exception:
                log.exception("Erro ao processar pedido")
                reply, record = lines.pick("error", self._sarcasm()) or "Algo correu mal.", False
            if record:
                try:
                    self.vault.daily_log(text, reply)
                except Exception:
                    pass
            self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            self.history = self.history[-12:]
        if speak:
            self.say(reply, cache=False)
        else:
            self.emit("reply", {"text": reply})
            self.set_state("idle")
        self.emit("hud", self.hud_state())
        return reply

    def _dispatch(self, text: str, source: str) -> tuple[str, bool]:
        if text.startswith("/"):
            return self._slash(text), False
        intent = self.matcher.match(text)
        if intent:
            return self._run_intent(intent, text)
        res = self.agent.run(text, self.history)
        return res.reply, True

    def _run_intent(self, it: Intent, text: str) -> tuple[str, bool]:
        if it.kind == "special":
            return self._special(it), False
        res = self.executor.execute(it.name, it.args, origin="intent", request=text)
        if not res.ok:
            return res.message, False
        if it.speak_result:
            return res.message, False
        return (lines.pick("done", self._sarcasm()) or "Feito."), False

    # ---------------------------------------------------------------- comandos especiais
    def _special(self, it: Intent) -> str:
        n, a, sar = it.name, it.args, self._sarcasm()
        if n == "panic":
            self.panic()
            return lines.pick("panic", sar)
        if n == "clear_panic":
            self.executor.clear_panic()
            return "Ações reativadas."
        if n in ("private_on", "private_off"):
            self.set_private(n == "private_on")
            return lines.pick(n, sar)
        if n == "switch_model":
            return self.switch_model(a.get("target", ""))
        if n == "sarcasm":
            lvl = a.get("level", sar + a.get("delta", 0))
            lvl = max(0, min(3, int(lvl)))
            self.cfg.set("personality.sarcasm", lvl)
            return {0: "Sarcasmo desligado. Estou a custo.", 1: "Sarcasmo baixo.", 2: "Sarcasmo normal.",
                    3: "Sarcasmo no máximo. Por tua conta e risco."}[lvl]
        if n == "audit_summary":
            return self.audit_summary()
        if n == "briefing":
            return self.agent.run("Executa a habilidade 'briefing-do-dia' e dá-me o briefing do dia.", self.history).reply
        if n == "help":
            fam = collections.OrderedDict()
            for s in REGISTRY.values():
                fam.setdefault(s.family, []).append(s.name)
            return "Sei fazer coisas nestas áreas: " + ", ".join(fam) + ". Pede-me só o que queres."
        return lines.pick("unknown", sar)

    def audit_summary(self) -> str:
        today = time.strftime("%Y-%m-%d")
        recs = [r for r in self.audit.tail(300) if r.get("event") == "action" and str(r.get("ts", "")).startswith(today)]
        if not recs:
            return "Hoje ainda não fiz nenhuma ação."
        ok = [r for r in recs if r.get("ok")]
        c = collections.Counter(r["action"] for r in ok)
        top = ", ".join(f"{n} ×{k}" for n, k in c.most_common(4))
        return f"Hoje fiz {len(ok)} ações com sucesso e {len(recs) - len(ok)} sem sucesso. Mais usadas: {top or 'nenhuma'}."

    def _slash(self, text: str) -> str:
        cmd, _, arg = text[1:].partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        skill = {"metricas": "metricas", "caixa": "caixa-de-entrada", "tendencias": "tendencias",
                 "plano": "plano-de-hoje", "vault": "vault"}.get(cmd)
        if skill:
            res = self.agent.run(f"Executa a habilidade '{skill}'. {arg}".strip(), self.history)
            return res.reply
        if cmd == "modelo":
            return self.switch_model(arg) if arg else "Perfis: " + ", ".join(self.llm.profiles()) + f". Ativo: {self.llm.active}."
        if cmd == "privado":
            on = arg.lower() not in ("off", "desligar", "0")
            self.set_private(on)
            return lines.pick("private_on" if on else "private_off", self._sarcasm())
        if cmd == "sarcasmo" and arg.isdigit():
            return self._special(Intent("special", "sarcasm", {"level": int(arg)}))
        if cmd in ("panico", "pânico", "parar"):
            return self._special(Intent("special", "panic", {}))
        if cmd in ("acoes", "ações"):
            return "Ações: " + ", ".join(sorted(s["function"]["name"] for s in self.executor.catalog()))
        if cmd == "cache" and self.tts is not None:
            n = sum(e.clear_cache() for e in self.tts.engines.values() if hasattr(e, "clear_cache"))
            return f"Cache apagada ({n} ficheiros)."
        if cmd == "seguro":
            self.session.mode = "normal" if self.session.mode == "safe" else "safe"
            self.emit("hud", self.hud_state())
            return f"Modo {'seguro' if self.session.mode == 'safe' else 'normal'}."
        if cmd in ("ajuda", "help"):
            return self._special(Intent("special", "help", {}))
        return "Comando desconhecido. Experimenta /ajuda."

    # ---------------------------------------------------------------- controlo
    def panic(self) -> None:
        self.executor.panic()
        if self.tts is not None:
            self.tts.stop()
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:
                pass
        self._cancel_listen.set()
        self.set_state("idle")
        self.emit("hud", self.hud_state())

    def set_private(self, on: bool) -> None:
        if self.tts is not None:
            self.tts.set_private(on)
        self.cfg.set("voice.tts.private_mode", on)
        self.emit("hud", self.hud_state())

    def _local_profile(self) -> str | None:
        profs = self.cfg.get("llm.profiles", {}) or {}
        fb = self.cfg.get("llm.fallback")
        if fb in profs:
            return fb
        for n, p in profs.items():
            if p.get("type") in ("llama_cpp", "transformers") or "localhost" in str(p.get("base_url", "")):
                return n
        return None

    def switch_model(self, target: str) -> str:
        target = target.strip().lower()
        profs = self.cfg.get("llm.profiles", {}) or {}
        if target in ("local", "offline"):
            name = self._local_profile()
        elif target in ("api", "cloud", "online"):
            name = next((n for n, p in profs.items() if p.get("type") == "openai_compat" and "localhost" not in str(p.get("base_url", ""))), None)
        else:
            name = target if target in profs else None
        if not name:
            return "Não encontrei esse modelo. Perfis: " + ", ".join(profs) + "."
        try:
            self.llm.switch(name)
        except Exception as e:
            return f"Não consegui mudar: {e}"
        self.cfg.set("llm.active", name)
        self.emit("hud", self.hud_state())
        return f"{lines.pick('model_switch', self._sarcasm())} Agora uso {name}."

    def _on_llm_fallback(self, from_: str, to: str) -> None:
        self.emit("notice", {"text": f"Modelo '{from_}' falhou; a usar '{to}'."})
        self._pending_notice = lines.pick("fallback", self._sarcasm())

    def _on_reminder(self, text: str) -> None:
        msg = f"{lines.pick('reminder', self._sarcasm())} {text}"
        self.emit("notice", {"text": msg})
        threading.Thread(target=self.say, args=(msg,), daemon=True).start()

    def _resolve_app_name(self, name: str) -> str | None:
        from .actions.apps import resolve_app
        r = resolve_app(self.ctx, name)
        return r[0] if r else None

    def run_scheduled(self, skill: str, speak: bool = True) -> None:
        self.audit.write(event="scheduled", skill=skill)
        self.handle_text(f"Executa a habilidade '{skill}' e resume o resultado em poucas frases.", source="scheduler", speak=speak)

    # ---------------------------------------------------------------- estado para o HUD
    def _plan_items(self) -> list[str]:
        try:
            txt = self.vault.read(f"outputs/plano-{time.strftime('%Y-%m-%d')}.md")
        except Exception:
            return []
        return [re.sub(r"^\d+\.\s*", "", l).strip() for l in txt.splitlines() if re.match(r"^\d+\.", l.strip())][:3]

    def hud_state(self) -> dict:
        prov_name = self.llm.active
        cloud = self.llm.is_cloud()
        try:
            model = getattr(self.llm.get(prov_name), "model", "") or prov_name
        except Exception:
            model = prov_name
        return {
            "user": self.cfg.get("user.name", ""),
            "llm": {"profile": prov_name, "model": model, "where": "API" if cloud else "LOCAL",
                    "fallback": self.llm.using_fallback},
            "voice": {"enabled": self.voice_enabled, "tts": self.tts.label() if self.tts else "OFF",
                      "stt": ("PRIVADO" if (self.tts and self.tts.private) else "CLOUD") if (self.stt and self.voice_enabled) else "OFF",
                      "chars_today": self.tts.chars_today() if self.tts else 0},
            "mode": "SIMULAÇÃO" if self.session.dry_run else ("SEGURO" if self.session.mode == "safe" else "NORMAL"),
            "panic": self.session.panic,
            "notes": self.vault.count(),
            "briefing": self.briefing.build(self),
            "skills": [{"name": s.name, "description": s.description} for s in self.skills.list()],
            "actions": [{"ts": r.get("ts", ""), "action": r.get("action"), "level": r.get("level"), "ok": r.get("ok"),
                         "outcome": r.get("outcome")} for r in self.audit.tail(40) if r.get("event") == "action"][-8:],
            "state": self.state,
            "uptime": int(time.time() - self.started),
        }

    # ---------------------------------------------------------------- arranque / fim
    def start(self, scheduler: bool = True) -> None:
        self.reminders.start()
        self.killswitch.install()
        if self.voice_enabled and self.recorder is not None:
            self._install_global_ptt()
        if scheduler and self.cfg.get("scheduler.enabled", True):
            from .scheduler import start_scheduler
            self._scheduler = start_scheduler(self)
        self.audit.write(event="start", mode=self.session.mode, dry_run=self.session.dry_run)

    def _install_global_ptt(self) -> None:
        try:
            import keyboard  # type: ignore
            key = self.cfg.get("voice.ptt.key", "f9")
            keyboard.on_press_key(key, lambda e: self.ptt_down() if self.state != "listening" else None)
            keyboard.on_release_key(key, lambda e: self.ptt_up() if self.state == "listening" else None)
        except Exception as e:
            log.info("Atalho global de voz indisponível (%s). Usa o HUD (barra de espaço / botão).", e)

    def stop(self) -> None:
        self.reminders.stop()
        sch = getattr(self, "_scheduler", None)
        if sch is not None:
            try:
                sch.shutdown(wait=False)
            except Exception:
                pass