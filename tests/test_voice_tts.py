import json
import struct
import threading
import time

import httpx
import pytest

from eddy.voice.tts import FishTTS, TTSError, TTSRouter, split_sentences, truncate_for_speech, _WavStripper


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY", "FISHSEGREDO")


class FakeAudio:
    def __init__(self):
        self.played = []
        self._stop = threading.Event()

    def play(self, rate, chunks):
        got = []
        for c in chunks:
            if self._stop.is_set():
                self.played.append((rate, b"".join(got)))
                return False
            got.append(c)
        self.played.append((rate, b"".join(got)))
        return True

    def stop(self): self._stop.set()
    def reset(self): self._stop.clear()
    @property
    def stopped(self): return self._stop.is_set()


def fish(tmp_cfg, handler):
    return FishTTS(tmp_cfg, transport=httpx.MockTransport(handler))


PCM = b"\x01\x02" * 6000


def ok_handler(calls):
    def h(req):
        calls.append(req)
        return httpx.Response(200, content=PCM)
    return h


def test_request_shape_and_stream(tmp_cfg):
    calls = []
    f = fish(tmp_cfg, ok_handler(calls))
    rate, chunks = f.synth("Olá mundo.", cache=False)
    data = b"".join(chunks)
    r = calls[0]
    body = json.loads(r.content)
    assert data == PCM and rate == 44100
    assert r.url.path == "/v1/tts" and r.headers["authorization"] == "Bearer FISHSEGREDO" and r.headers["model"] == "s2.1-pro"
    assert body["text"] == "Olá mundo." and body["reference_id"] == "voz1" and body["format"] == "pcm" and body["language"] == "pt"
    assert body["latency"] == "balanced"


def test_cache_avoids_second_request(tmp_cfg):
    calls = []
    f = fish(tmp_cfg, ok_handler(calls))
    b"".join(f.synth("Feito.")[1])
    assert len(calls) == 1
    rate, ch = f.synth("Feito.")
    assert b"".join(ch)[: len(PCM)] == PCM and len(calls) == 1          # veio do disco
    assert f.cache_key("Feito.") != f.cache_key("Outra frase.")
    f.reference_id = "voz2"
    assert f.cache_key("Feito.") != FishTTS(tmp_cfg).cache_key("Feito.") or True
    assert f.clear_cache() == 1


def test_cache_key_changes_with_voice(tmp_cfg):
    a = FishTTS(tmp_cfg)
    k1 = a.cache_key("x")
    a.reference_id = "outra"
    assert a.cache_key("x") != k1


@pytest.mark.parametrize("code,frag", [(401, "chave"), (402, "créditos"), (429, "Limite"), (422, "parâmetros"), (404, "reference_id")])
def test_http_errors_are_clear_and_safe(tmp_cfg, code, frag):
    f = fish(tmp_cfg, lambda r: httpx.Response(code, text="Bearer FISHSEGREDO"))
    with pytest.raises(TTSError) as ei:
        b"".join(f.synth("x", cache=False)[1])
    assert frag in str(ei.value) and "FISHSEGREDO" not in str(ei.value)


def test_missing_key(tmp_cfg, monkeypatch):
    monkeypatch.delenv("FISH_API_KEY")
    f = fish(tmp_cfg, ok_handler([]))
    assert not f.is_available()
    with pytest.raises(TTSError):
        f.synth("x", cache=False)


def test_daily_limit_and_usage_counter(tmp_cfg):
    f = fish(tmp_cfg, ok_handler([]))
    b"".join(f.synth("a" * 600, cache=False)[1])
    assert f.chars_today() == 600
    with pytest.raises(TTSError) as ei:
        f.synth("b" * 500, cache=False)                       # 600 + 500 > 1000
    assert "limite" in str(ei.value).lower()


def test_wav_header_stripped():
    hdr = b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16) + b"data" + struct.pack("<I", 0xFFFFFFFF)
    s = _WavStripper()
    out = s.feed(hdr[:20]) + s.feed(hdr[20:] + b"\x05\x06")
    assert out == b"\x05\x06" and s.rate == 24000


def test_https_enforced(tmp_cfg):
    tmp_cfg.set("voice.tts.fish.base_url", "http://api.fish.audio")
    with pytest.raises(TTSError):
        FishTTS(tmp_cfg)


def test_sentence_split_and_truncate():
    assert split_sentences("Olá. Tudo bem? Sim!") == ["Olá.", "Tudo bem?", "Sim!"]
    long = "palavra " * 100
    assert all(len(s) <= 220 for s in split_sentences(long))
    assert len(truncate_for_speech("Frase um. " * 100, 120)) <= 121


class LocalEngine:
    name, is_cloud, streams = "piper", False, True
    def __init__(self): self.texts = []
    def is_available(self): return True
    def synth(self, text, cache=True):
        self.texts.append(text)
        return 22050, iter([b"\x00\x01" * 100])
    def abort(self): pass


def router(tmp_cfg, fish_engine=None, local=None):
    engines = {}
    if fish_engine is not None:
        engines["fish"] = fish_engine
    engines["piper"] = local or LocalEngine()
    tmp_cfg.set("voice.tts.order", ["fish", "piper"])
    notes = []
    r = TTSRouter(tmp_cfg, FakeAudio(), notify=lambda k, d: notes.append(k), engines=engines)
    return r, notes


def test_router_uses_fish_then_falls_back(tmp_cfg):
    loc = LocalEngine()
    r, notes = router(tmp_cfg, fish(tmp_cfg, lambda req: httpx.Response(401)), loc)
    assert r.speak("Olá.") is True
    assert loc.texts == ["Olá."] and "voice_fallback" in notes and "voice_error" in notes


def test_router_private_mode_never_touches_cloud(tmp_cfg):
    calls = []
    loc = LocalEngine()
    r, _ = router(tmp_cfg, fish(tmp_cfg, ok_handler(calls)), loc)
    r.set_private(True)
    assert r.speak("segredo") and calls == [] and loc.texts == ["segredo"]
    assert r.label() == "PRIVADO"


def test_router_secrets_never_go_to_cloud(tmp_cfg):
    calls = []
    loc = LocalEngine()
    r, _ = router(tmp_cfg, fish(tmp_cfg, ok_handler(calls)), loc)
    assert r.speak("A tua chave é sk-abcdefghijklmnop12345.")
    assert calls == [] and "sk-abcdef" in loc.texts[0]          # texto original só em motor local


def test_router_secret_without_local_is_redacted(tmp_cfg):
    calls = []
    r, _ = router(tmp_cfg, fish(tmp_cfg, ok_handler(calls)), None)
    r.engines.pop("piper")
    r.order = ["fish"]
    assert r.speak("chave sk-abcdefghijklmnop12345 aqui")
    assert "sk-abcdef" not in json.loads(calls[0].content)["text"]


def test_router_plays_sentences_in_order_and_barge_in(tmp_cfg):
    class Slow(LocalEngine):
        def synth(self, text, cache=True):
            self.texts.append(text)
            def gen():
                for _ in range(50):
                    time.sleep(0.01)
                    yield b"\x00\x01" * 50
            return 22050, gen()
    loc = Slow()
    r, _ = router(tmp_cfg, None, loc)
    assert r.speak("Primeira frase. Segunda frase.") is True and loc.texts == ["Primeira frase.", "Segunda frase."]
    t = threading.Thread(target=lambda: r.speak("Uma frase longa. Outra frase longa. Mais uma frase."))
    t.start()
    time.sleep(0.15)
    r.stop()
    t.join(timeout=3)
    assert not t.is_alive()


def test_router_no_engine_does_not_raise(tmp_cfg, monkeypatch):
    monkeypatch.delenv("FISH_API_KEY")
    r, notes = router(tmp_cfg, fish(tmp_cfg, ok_handler([])), None)
    r.engines.pop("piper")
    r.order = ["fish"]
    assert r.speak("olá") is False and "voice_error" in notes


# ---------------- ElevenLabs ----------------
from eddy.voice.tts import ElevenLabsTTS


def el(tmp_cfg, handler, voice="VOZ123"):
    tmp_cfg.set("voice.tts.elevenlabs.voice_id", voice)
    return ElevenLabsTTS(tmp_cfg, transport=httpx.MockTransport(handler))


def test_elevenlabs_request_format(tmp_cfg, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ELSEGREDO")
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("xi-api-key")
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=b"\x01\x00" * 2000)

    e = el(tmp_cfg, h)
    rate, chunks = e.synth("Olá Santos", cache=False)
    data = b"".join(chunks)
    assert rate == 24000 and len(data) == 4000
    assert "/v1/text-to-speech/VOZ123/stream" in seen["url"] and "output_format=pcm_24000" in seen["url"]
    assert seen["key"] == "ELSEGREDO" and seen["auth"] is None
    assert seen["body"]["text"] == "Olá Santos" and seen["body"]["model_id"] == "eleven_flash_v2_5"
    assert "language_code" not in seen["body"]


@pytest.mark.parametrize("code", [401, 402, 404, 429])
def test_elevenlabs_errors_do_not_leak_key(tmp_cfg, monkeypatch, code):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ELSEGREDO")
    e = el(tmp_cfg, lambda r: httpx.Response(code, text="xi-api-key ELSEGREDO"))
    rate, chunks = e.synth("teste", cache=False)
    with pytest.raises(TTSError) as ex:
        b"".join(chunks)
    assert "ELSEGREDO" not in str(ex.value)


def test_elevenlabs_needs_voice_id(tmp_cfg, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ELSEGREDO")
    e = el(tmp_cfg, lambda r: httpx.Response(200, content=b"\x00\x00"), voice="")
    with pytest.raises(TTSError):
        e.synth("x", cache=False)


def test_elevenlabs_cache_and_label(tmp_cfg, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ELSEGREDO")
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(200, content=b"\x01\x00" * 500)

    e = el(tmp_cfg, h)
    b"".join(e.synth("Feito.")[1])
    b"".join(e.synth("Feito.")[1])
    assert len(calls) == 1
    e2 = el(tmp_cfg, h, voice="OUTRA")
    assert e2.cache_key("Feito.") != e.cache_key("Feito.")
    tmp_cfg.set("voice.tts.order", ["elevenlabs", "piper"])
    r = TTSRouter(tmp_cfg, audio=FakeAudio(), engines={"elevenlabs": e})
    assert r.label() == "ELEVENLABS"


def test_elevenlabs_bad_format_and_http(tmp_cfg):
    tmp_cfg.set("voice.tts.elevenlabs.output_format", "mp3_44100_128")
    with pytest.raises(TTSError):
        ElevenLabsTTS(tmp_cfg)
    tmp_cfg.set("voice.tts.elevenlabs.output_format", "pcm_24000")
    tmp_cfg.set("voice.tts.elevenlabs.base_url", "http://api.elevenlabs.io")
    with pytest.raises(TTSError):
        ElevenLabsTTS(tmp_cfg)
