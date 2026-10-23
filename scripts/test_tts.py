"""Testa a voz na cloud (Gemini / ElevenLabs): sintetiza 3 frases, mede o tempo e guarda WAV em logs/tts_test/.
Com --stt, grava 4 s do microfone e mostra a transcrição de cada motor com o tempo.

Uso:  python scripts/test_voice.py [--engine gemini|elevenlabs] [--play] [--stt]
"""
from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PHRASES = [
    "Olá Santos, estou a ouvir. Em que posso ajudar?",
    "Tens três lembretes para hoje: às oito e meia, ao meio-dia e às dezanove horas.",
    "Amanhã de manhã, a Lisboa e a Amadora vão ter sol, com máxima de vinte e dois graus.",
]


def load_env() -> None:
    import os
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["gemini", "elevenlabs"], default="gemini")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--stt", action="store_true")
    a = ap.parse_args()
    load_env()
    from eddy.config import Config
    from eddy.voice.tts import ElevenLabsTTS, GeminiTTS, TTSError
    cfg = Config.load()
    eng = (GeminiTTS if a.engine == "gemini" else ElevenLabsTTS)(cfg)
    if not eng.is_available():
        print(f"Falta a chave de {a.engine} no .env.")
        return 1
    out = ROOT / "logs" / "tts_test"
    out.mkdir(parents=True, exist_ok=True)
    for i, ph in enumerate(PHRASES, 1):
        t0 = time.time()
        try:
            rate, chunks = eng.synth(ph, cache=False)
            pcm = b"".join(chunks)
        except TTSError as e:
            print(f"[{i}] ERRO: {e}")
            return 2
        dt = time.time() - t0
        f = out / f"{a.engine}_{i}.wav"
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm[: len(pcm) - len(pcm) % 2])
        print(f"[{i}] {dt:4.1f}s para {len(pcm) / 2 / rate:4.1f}s de áudio → {f}")
        if a.play:
            from eddy.voice.audio import AudioOut
            AudioOut().play(rate, [pcm])
    if a.stt:
        import sounddevice as sd
        from eddy.voice.stt import SR, STT, STTError
        print("\nFala agora durante 4 s...")
        rec = sd.rec(4 * SR, samplerate=SR, channels=1, dtype="float32", device=cfg.get("voice.stt.input_device", None))
        sd.wait()
        stt = STT(cfg)
        for name in stt.order:
            e = stt.engines[name]
            if not e.available():
                print(f"  {name}: sem chave")
                continue
            t0 = time.time()
            try:
                txt = e.transcribe(rec[:, 0], cfg.get("voice.stt.language", "pt"))
                print(f"  {name}: {time.time() - t0:.1f}s → «{txt}»")
            except STTError as err:
                print(f"  {name}: ERRO {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())