"""TTS só cloud: Gemini → ElevenLabs (→ Fish Audio, opcional), com cache, redação de segredos e interrupção."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import queue
import re
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Iterator

import httpx
import numpy as np

from ..config import Config
from ..security.sanitize import redact_for_cloud
from .audio import AudioError, AudioOut

log = logging.getLogger("eddy.tts")


class TTSError(RuntimeError):
    """Erro de voz com mensagem em português e sem segredos."""


_SENT = re.compile(r"(?<=[\.\!\?…])\s+|\n+")


def split_sentences(text: str, max_len: int = 220) -> list[str]:
    out: list[str] = []
    for part in _SENT.split(text.strip()):
        part = part.strip()
        while len(part) > max_len:
            cut = part.rfind(",", 0, max_len)
            cut = cut if cut > 40 else part.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            out.append(part[:cut].strip())
            part = part[cut:].lstrip(", ")
        if part:
            out.append(part)
    return out


def truncate_for_speech(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = max(text.rfind(". ", 0, max_chars), text.rfind("! ", 0, max_chars), text.rfind("? ", 0, max_chars))
    return text[: cut + 1] if cut > 60 else text[:max_chars].rsplit(" ", 1)[0] + "…"


class _WavStripper:
    """Remove o cabeçalho WAV de um fluxo e descobre a taxa de amostragem."""
    def __init__(self):
        self.buf = b""
        self.done = False
        self.rate: int | None = None

    def feed(self, chunk: bytes) -> bytes:
        if self.done:
            return chunk
        self.buf += chunk
        i = self.buf.find(b"data")
        if i == -1 or len(self.buf) < i + 8:
            if len(self.buf) > 8192:
                raise TTSError("Resposta de áudio WAV inválida.")
            return b""
        if len(self.buf) >= 28:
            self.rate = int.from_bytes(self.buf[24:28], "little")
        self.done = True
        rest = self.buf[i + 8:]
        self.buf = b""
        return rest


class FishTTS:
    name = "fish"
    is_cloud = True
    streams = True

    def __init__(self, cfg: Config, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        f = cfg.get("voice.tts.fish", {}) or {}
        self.base = str(f.get("base_url", "https://api.fish.audio")).rstrip("/")
        if not self.base.startswith("https://"):
            raise TTSError("A Fish Audio tem de usar HTTPS.")
        self.model = f.get("model", "s2.1-pro")
        self.reference_id = f.get("reference_id", "") or None
        self.language = f.get("language", "pt")
        self.fmt = f.get("format", "pcm")
        self.rate = int(f.get("sample_rate", 44100))
        self.latency = f.get("latency", "balanced")
        self.limit = int(f.get("daily_char_limit", 0) or 0)
        self.key_env = f.get("api_key_env", "FISH_API_KEY")
        self.timeout = httpx.Timeout(float(f.get("timeout_read_s", 15)), connect=float(f.get("timeout_connect_s", 3)))
        self.cache_dir = cfg.path(cfg.get("voice.tts.cache_dir", "cache/tts"))
        self.usage_path = cfg.path("logs/tts_usage.json")
        self._client = httpx.Client(timeout=self.timeout, transport=transport)
        self._resp: httpx.Response | None = None

    # -- estado ------------------------------------------------------
    def is_available(self) -> bool:
        return bool(Config.secret(self.key_env))

    def _usage(self) -> dict:
        try:
            return json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def chars_today(self) -> int:
        return int(self._usage().get(time.strftime("%Y-%m-%d"), 0))

    def _add_usage(self, n: int) -> None:
        u = self._usage()
        day = time.strftime("%Y-%m-%d")
        u = {k: v for k, v in u.items() if k >= time.strftime("%Y-%m-01")}  # só o mês corrente
        u[day] = int(u.get(day, 0)) + n
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage_path.write_text(json.dumps(u), encoding="utf-8")

    # -- cache -------------------------------------------------------
    def cache_key(self, text: str) -> str:
        blob = json.dumps([text, self.reference_id, self.model, self.language, self.fmt, self.rate], ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def _cache_path(self, text: str) -> Path:
        return self.cache_dir / f"{self.cache_key(text)}.wav"

    def clear_cache(self) -> int:
        n = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.wav"):
                f.unlink()
                n += 1
        return n

    # -- síntese -----------------------------------------------------
    def synth(self, text: str, cache: bool = True) -> tuple[int, Iterator[bytes]]:
        path = self._cache_path(text)
        if cache and path.exists():
            with wave.open(str(path), "rb") as w:
                rate, data = w.getframerate(), w.readframes(w.getnframes())
            return rate, iter([data[i:i + 8192] for i in range(0, len(data), 8192)])
        key = Config.secret(self.key_env)
        if not key:
            raise TTSError("Falta a FISH_API_KEY no .env.")
        if self.limit and self.chars_today() + len(text) > self.limit:
            raise TTSError("Atingi o limite diário de caracteres da voz na cloud.")
        return self.rate, self._stream(text, key, path if cache and len(text) <= 200 else None)

    def _stream(self, text: str, key: str, cache_to: Path | None) -> Iterator[bytes]:
        body = {"text": text, "format": self.fmt, "sample_rate": self.rate, "latency": self.latency,
                "language": self.language, "normalize": True}
        if self.reference_id:
            body["reference_id"] = self.reference_id
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "model": self.model}
        collected = bytearray()
        strip = _WavStripper() if self.fmt == "wav" else None
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                with self._client.stream("POST", f"{self.base}/v1/tts", json=body, headers=headers) as r:
                    self._resp = r
                    if r.status_code != 200:
                        r.read()
                        raise self._http_error(r.status_code)
                    for chunk in r.iter_bytes(4096):
                        if strip:
                            chunk = strip.feed(chunk)
                        if chunk:
                            collected += chunk
                            yield chunk
                self._add_usage(len(text))
                if cache_to is not None and collected:
                    self._save_cache(cache_to, bytes(collected), (strip.rate if strip and strip.rate else self.rate))
                return
            except TTSError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if collected:      # já começou a tocar: não repetir
                    return
                last_exc = e
                time.sleep(0.4)
            finally:
                self._resp = None
        raise TTSError(f"Sem ligação à Fish Audio ({type(last_exc).__name__}).")

    @staticmethod
    def _http_error(code: int) -> TTSError:
        msgs = {401: "A Fish Audio recusou a chave (401). Verifica a FISH_API_KEY.",
                402: "Sem créditos na Fish Audio (402).",
                403: "A Fish Audio recusou o acesso (403).",
                404: "Voz ou endpoint não encontrado na Fish Audio (404). Verifica o reference_id.",
                422: "A Fish Audio não aceitou os parâmetros (422). Verifica modelo/formato/voz.",
                429: "Limite de pedidos da Fish Audio atingido (429)."}
        return TTSError(msgs.get(code, f"Erro da Fish Audio ({code})."))

    def _save_cache(self, path: Path, pcm: bytes, rate: int) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm[: len(pcm) - (len(pcm) % 2)])
        except OSError:
            pass

    def abort(self) -> None:
        r = self._resp
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


class ElevenLabsTTS(FishTTS):
    """ElevenLabs (cloud): POST /v1/text-to-speech/{voice_id}/stream com áudio PCM em streaming."""
    name = "elevenlabs"
    is_cloud = True
    streams = True
    LABEL = "ELEVENLABS"
    _PCM_RATES = {"pcm_8000": 8000, "pcm_16000": 16000, "pcm_22050": 22050, "pcm_24000": 24000, "pcm_44100": 44100}

    def __init__(self, cfg: Config, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        f = cfg.get("voice.tts.elevenlabs", {}) or {}
        self.base = str(f.get("base_url", "https://api.elevenlabs.io")).rstrip("/")
        if not self.base.startswith("https://"):
            raise TTSError("A ElevenLabs tem de usar HTTPS.")
        self.model = f.get("model", "eleven_flash_v2_5")
        self.reference_id = f.get("voice_id", "") or None
        self.language = f.get("language_code", "") or ""
        self.fmt = str(f.get("output_format", "pcm_24000"))
        if self.fmt not in self._PCM_RATES:
            raise TTSError(f"output_format inválido ({self.fmt}). Usa um destes: {', '.join(self._PCM_RATES)}.")
        self.rate = self._PCM_RATES[self.fmt]
        vs = f.get("voice_settings", {}) or {}
        self.voice_settings = {k: vs[k] for k in ("stability", "similarity_boost", "style", "use_speaker_boost", "speed") if k in vs}
        self.limit = int(f.get("daily_char_limit", 0) or 0)
        self.key_env = f.get("api_key_env", "ELEVENLABS_API_KEY")
        self.timeout = httpx.Timeout(float(f.get("timeout_read_s", 15)), connect=float(f.get("timeout_connect_s", 3)))
        self.cache_dir = cfg.path(cfg.get("voice.tts.cache_dir", "cache/tts"))
        self.usage_path = cfg.path("logs/tts_usage_elevenlabs.json")
        self._client = httpx.Client(timeout=self.timeout, transport=transport)
        self._resp: httpx.Response | None = None

    def cache_key(self, text: str) -> str:
        blob = json.dumps(["el", text, self.reference_id, self.model, self.language, self.fmt, self.voice_settings],
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def synth(self, text: str, cache: bool = True) -> tuple[int, Iterator[bytes]]:
        if not self.reference_id and not (cache and self._cache_path(text).exists()):
            raise TTSError("Falta o voice_id da ElevenLabs no config.yaml (voice.tts.elevenlabs.voice_id).")
        return super().synth(text, cache)

    def _stream(self, text: str, key: str, cache_to: Path | None) -> Iterator[bytes]:
        body: dict = {"text": text, "model_id": self.model}
        if self.language:
            body["language_code"] = self.language
        if self.voice_settings:
            body["voice_settings"] = self.voice_settings
        headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "application/octet-stream"}
        url = f"{self.base}/v1/text-to-speech/{self.reference_id}/stream"
        collected = bytearray()
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                with self._client.stream("POST", url, params={"output_format": self.fmt}, json=body, headers=headers) as r:
                    self._resp = r
                    if r.status_code != 200:
                        r.read()
                        raise self._http_error(r.status_code)
                    for chunk in r.iter_bytes(4096):
                        if chunk:
                            collected += chunk
                            yield chunk
                self._add_usage(len(text))
                if cache_to is not None and collected:
                    self._save_cache(cache_to, bytes(collected), self.rate)
                return
            except TTSError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if collected:
                    return
                last_exc = e
                time.sleep(0.4)
            finally:
                self._resp = None
        raise TTSError(f"Sem ligação à ElevenLabs ({type(last_exc).__name__}).")

    @staticmethod
    def _http_error(code: int) -> TTSError:
        msgs = {400: "A ElevenLabs não aceitou o pedido (400). Se usas language_code, só alguns modelos o aceitam: deixa-o vazio.",
                401: "A ElevenLabs recusou a chave (401). Verifica a ELEVENLABS_API_KEY. Com pcm_44100 precisas de plano Pro: tenta pcm_24000.",
                402: "Pagamento necessário na ElevenLabs (402): voz de biblioteca só em planos pagos.",
                403: "A ElevenLabs recusou o acesso (403).",
                404: "Voz não encontrada na ElevenLabs (404). Verifica o voice_id.",
                422: "A ElevenLabs não aceitou os parâmetros (422). Verifica modelo, voice_id e output_format.",
                429: "Limite de pedidos ou de créditos da ElevenLabs atingido (429)."}
        return TTSError(msgs.get(code, f"Erro da ElevenLabs ({code})."))


def parse_wav(data: bytes) -> tuple[int, bytes]:
    """Lê um WAV (PCM 16 bits, 24 bits, 32 bits ou float32; mono ou estéreo) e devolve (taxa, PCM16 mono)."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise TTSError("A resposta de áudio não é um WAV válido.")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + size] if size != 0xFFFFFFFF else data[pos + 8:]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            pcm = body
            break
        pos += 8 + size + (size & 1)
    if fmt is None or pcm is None or len(fmt) < 16:
        raise TTSError("WAV incompleto.")
    tag = int.from_bytes(fmt[0:2], "little")
    ch = max(1, int.from_bytes(fmt[2:4], "little"))
    rate = int.from_bytes(fmt[4:8], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if tag == 0xFFFE and len(fmt) >= 26:          # WAVE_FORMAT_EXTENSIBLE
        tag = int.from_bytes(fmt[24:26], "little")
    if tag == 1 and bits == 16:
        x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0
    elif tag == 1 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 4], dtype="<i4").astype(np.float32) / 2147483648.0
    elif tag == 1 and bits == 24:
        raw = np.frombuffer(pcm[: len(pcm) - len(pcm) % 3], dtype=np.uint8).reshape(-1, 3)
        v = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / 8388608.0
    elif tag == 3 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 4], dtype="<f4").astype(np.float32)
    else:
        raise TTSError(f"Formato WAV não suportado (tag={tag}, bits={bits}).")
    if ch > 1:
        x = x[: len(x) - len(x) % ch].reshape(-1, ch).mean(axis=1)
    return rate, (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _find_audio(node) -> str | None:
    """Procura o último bloco de áudio (base64) numa resposta JSON da Gemini, seja qual for a profundidade."""
    found: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            d = n.get("data")
            if isinstance(d, str) and (n.get("type") == "audio" or str(n.get("mime_type", "")).startswith("audio")):
                found.append(d)
            for k in ("inlineData", "inline_data"):
                v = n.get(k)
                if isinstance(v, dict) and isinstance(v.get("data"), str):
                    found.append(v["data"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return found[-1] if found else None


class GeminiTTS(FishTTS):
    """Gemini TTS (cloud, Interactions API): POST /v1beta/interactions com response_format audio."""
    name = "gemini"
    is_cloud = True
    streams = True
    LABEL = "GEMINI"

    def __init__(self, cfg: Config, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        f = cfg.get("voice.tts.gemini", {}) or {}
        self.base = str(f.get("base_url", "https://generativelanguage.googleapis.com")).rstrip("/")
        if not self.base.startswith("https://"):
            raise TTSError("A Gemini tem de usar HTTPS.")
        self.model = f.get("model", "gemini-3.8-flash-tts")
        self.reference_id = f.get("voice", "Kore") or "Kore"
        self.language = f.get("language", "") or ""
        self.fmt = "wav"
        self.rate = 24000
        self.limit = int(f.get("daily_char_limit", 0) or 0)
        self.key_env = f.get("api_key_env", "GEMINI_API_KEY")
        self.timeout = httpx.Timeout(float(f.get("timeout_read_s", 30)), connect=float(f.get("timeout_connect_s", 3)))
        self.cache_dir = cfg.path(cfg.get("voice.tts.cache_dir", "cache/tts"))
        self.usage_path = cfg.path("logs/tts_usage_gemini.json")
        self._client = httpx.Client(timeout=self.timeout, transport=transport)
        self._resp: httpx.Response | None = None

    def cache_key(self, text: str) -> str:
        blob = json.dumps(["gm", text, self.reference_id, self.model, self.language], ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def synth(self, text: str, cache: bool = True) -> tuple[int, Iterator[bytes]]:
        path = self._cache_path(text)
        if cache and path.exists():
            with wave.open(str(path), "rb") as w:
                rate, data = w.getframerate(), w.readframes(w.getnframes())
            return rate, iter([data[i:i + 8192] for i in range(0, len(data), 8192)])
        key = Config.secret(self.key_env)
        if not key:
            raise TTSError("Falta a GEMINI_API_KEY no .env.")
        if self.limit and self.chars_today() + len(text) > self.limit:
            raise TTSError("Atingi o limite diário de caracteres da voz na cloud.")
        voice: dict = {"voice": self.reference_id}
        if self.language:
            voice["language"] = self.language
        body = {"model": self.model,
                "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [voice]}}
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        last: Exception | None = None
        r = None
        for attempt in range(2):
            try:
                r = self._client.post(f"{self.base}/v1beta/interactions", json=body, headers=headers)
                if r.status_code < 500:
                    break
                last = TTSError(f"Erro do servidor da Gemini ({r.status_code}).")
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
            time.sleep(0.4)
        else:
            raise TTSError(f"Sem ligação à Gemini ({type(last).__name__}).") if not isinstance(last, TTSError) else last
        if r.status_code != 200:
            raise self._http_error(r.status_code)
        try:
            b64 = _find_audio(r.json())
        except ValueError as e:
            raise TTSError("Resposta inválida da Gemini.") from e
        if not b64:
            raise TTSError("A Gemini não devolveu áudio (o modelo de voz está correto?).")
        try:
            raw = base64.b64decode(b64)
        except (ValueError, TypeError) as e:
            raise TTSError("Áudio da Gemini corrompido.") from e
        rate, pcm = parse_wav(raw) if raw[:4] == b"RIFF" else (24000, raw[: len(raw) - len(raw) % 2])
        if not pcm:
            raise TTSError("A Gemini devolveu áudio vazio.")
        self._add_usage(len(text))
        if cache and len(text) <= 200:
            self._save_cache(path, pcm, rate)
        return rate, iter([pcm[i:i + 8192] for i in range(0, len(pcm), 8192)])

    @staticmethod
    def _http_error(code: int) -> TTSError:
        msgs = {400: "A Gemini não aceitou o pedido de voz (400). Verifica o modelo e o nome da voz no config.yaml.",
                401: "A Gemini recusou a chave (401). Verifica a GEMINI_API_KEY.",
                403: "A Gemini recusou o acesso (403): chave sem permissão ou região não suportada.",
                404: "Modelo de voz não encontrado na Gemini (404). Verifica voice.tts.gemini.model.",
                429: "Limite de pedidos ou quota da Gemini atingido (429)."}
        return TTSError(msgs.get(code, f"Erro da Gemini ({code})."))


class TTSRouter:
    """Escolhe o motor, protege segredos, faz pipeline frase-a-frase e fallback."""

    def __init__(self, cfg: Config, audio: AudioOut | None = None, notify: Callable[[str, dict], None] | None = None,
                 engines: dict | None = None):
        self.cfg = cfg
        self.audio = audio or AudioOut()
        self.notify = notify or (lambda *_: None)
        self.private = bool(cfg.get("voice.tts.private_mode", False))
        self.max_chars = int(cfg.get("voice.tts.max_chars", 500))
        self.engines = engines if engines is not None else self._build()
        self.order = [n for n in cfg.get("voice.tts.order", ["gemini", "elevenlabs"]) if n in self.engines]
        self.current = ""
        self._warned_fallback = False
        self._speaking = threading.Event()

    def _build(self) -> dict:
        eng: dict = {}
        for name, cls in (("gemini", GeminiTTS), ("elevenlabs", ElevenLabsTTS), ("fish", FishTTS)):
            try:
                eng[name] = cls(self.cfg)
            except TTSError as e:
                log.warning("TTS %s desativado: %s", name, e)
        return eng

    def set_private(self, on: bool) -> None:
        self.private = on

    def usable(self, local_only: bool = False) -> list:
        out = []
        for n in self.order:
            e = self.engines[n]
            if (self.private or local_only) and e.is_cloud:
                continue
            try:
                if e.is_available():
                    out.append(e)
            except Exception:
                continue
        return out

    def label(self) -> str:
        if self.private:
            return "PRIVADO"
        u = self.usable()
        if not u:
            return "SEM VOZ"
        return getattr(u[0], "LABEL", "FISH" if u[0].is_cloud else "LOCAL")

    def chars_today(self) -> int:
        for n in self.order:
            e = self.engines[n]
            if e.is_cloud and hasattr(e, "chars_today"):
                return e.chars_today()
        return 0

    # -- fala --------------------------------------------------------
    def stop(self) -> None:
        self.audio.stop()
        for e in self.engines.values():
            try:
                e.abort()
            except Exception:
                pass

    def speak(self, text: str, cache: bool = True) -> bool:
        """Fala o texto. Devolve True se falou até ao fim. Nunca levanta exceções para o chamador."""
        text = truncate_for_speech(" ".join(text.split()), self.max_chars)
        if not text:
            return True
        self.audio.reset()
        self._speaking.set()
        try:
            return self._speak(text, cache)
        except Exception as e:
            log.warning("Falha de voz: %s", e)
            self.notify("voice_error", {"message": str(e)[:200]})
            return False
        finally:
            self._speaking.clear()

    def _speak(self, text: str, cache: bool) -> bool:
        engines = self.usable()
        if not engines:
            if self.private:
                log.info("Modo privado: sem voz (nada vai para a cloud).")
                return True
            raise TTSError("Nenhum motor de voz disponível. Define GEMINI_API_KEY ou ELEVENLABS_API_KEY no .env.")
        # Segredos nunca vão para a cloud: se o texto tiver algo sensível, usa motor local com o texto original.
        redacted, changed = redact_for_cloud(text)
        for i, e in enumerate(engines):
            use_text = text
            if e.is_cloud and changed:
                local = [x for x in engines if not x.is_cloud]
                if local:
                    continue          # deixa o motor local tratar o texto original
                use_text = redacted
            try:
                self.current = e.name
                if i > 0 and not self._warned_fallback and engines[0].is_cloud:
                    self._warned_fallback = True
                    self.notify("voice_fallback", {"engine": e.name})
                return self._run_engine(e, use_text, cache)
            except (TTSError, AudioError, httpx.HTTPError, OSError) as err:
                log.warning("Motor %s falhou: %s", e.name, err)
                self.notify("voice_error", {"message": str(err)[:200], "engine": e.name})
                if self.audio.stopped:
                    return False
                continue
        return False

    def _run_engine(self, e, text: str, cache: bool) -> bool:
        if not e.streams:
            e.speak_blocking(text)
            return True
        sentences = split_sentences(text)
        q: queue.Queue = queue.Queue(maxsize=256)
        err: list[Exception] = []
        DONE = object()

        def producer():
            try:
                for s in sentences:
                    if self.audio.stopped:
                        break
                    rate, chunks = e.synth(s, cache=cache)
                    for c in chunks:
                        if self.audio.stopped:
                            break
                        q.put((rate, c))
            except Exception as ex:  # noqa: BLE001
                err.append(ex)
            finally:
                q.put(DONE)

        t = threading.Thread(target=producer, daemon=True, name="tts-producer")
        t.start()

        # Reprodução contínua com a taxa da primeira frase (a taxa vem do primeiro bloco).
        first = q.get()
        if first is DONE:
            if err:
                raise err[0]
            return True
        rate0, c0 = first

        def gen():
            yield c0
            while True:
                item = q.get()
                if item is DONE:
                    return
                yield item[1]

        try:
            finished = self.audio.play(rate0, gen())
        finally:
            if self.audio.stopped:
                e.abort()
        t.join(timeout=2)
        if err:
            raise err[0]
        return finished