"""Mede a latencia REAL do STT e do TTS (VoiceStudio e reserva) com a tua voz.

Uso:  python scripts/bench_voice.py            # TTS + STT (grava 4 s do microfone)
      python scripts/bench_voice.py --no-mic   # só TTS (usa uma frase gerada como entrada do STT)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PHRASES = ["Olá Santos, estou a ouvir.", "Abre o Chrome e baixa o volume para trinta por cento."]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--seconds", type=float, default=4.0)
    a = ap.parse_args()
    import numpy as np
    from eddy.config import Config
    from eddy.voice.stt import STT, SR, STTError
    from eddy.voice.tts import TTSError, VoiceStudioTTS

    cfg = Config.load()
    print("== TTS (VoiceStudio) ==")
    tts = VoiceStudioTTS(cfg)
    audio_for_stt = None
    if not tts.is_available():
        print("VoiceStudio não responde em", tts.base, "- abre-o e tenta outra vez.")
    else:
        for ph in PHRASES:
            t0 = time.time()
            try:
                rate, chunks = tts.synth(ph, cache=False)
                pcm = b"".join(chunks)
            except TTSError as e:
                print("ERRO:", e)
                break
            dt = time.time() - t0
            dur = len(pcm) / 2 / rate
            print(f"  {dt:5.2f}s para {dur:4.1f}s de áudio (fator {dt / max(dur, 0.01):.2f}x)  «{ph}»")
            if audio_for_stt is None:
                x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
                audio_for_stt = np.interp(np.linspace(0, len(x), int(len(x) * SR / rate), endpoint=False),
                                          np.arange(len(x)), x).astype(np.float32)
    print("\n== STT ==")
    audio = None
    if not a.no_mic:
        import sounddevice as sd
        print(f"Fala agora durante {a.seconds:.0f} s...")
        audio = sd.rec(int(a.seconds * SR), samplerate=SR, channels=1, dtype="float32",
                       device=cfg.get("voice.stt.input_device", None))
        sd.wait()
        audio = audio[:, 0]
    else:
        audio = audio_for_stt
    if audio is None:
        print("Sem áudio para testar.")
        return 1
    stt = STT(cfg)
    for name in stt.order:
        e = stt.engines[name]
        if not e.available():
            print(f"  {name}: indisponível")
            continue
        for rnd in (1, 2):                      # a 1.ª inclui o carregamento do modelo
            t0 = time.time()
            try:
                text = e.transcribe(audio, cfg.get("voice.stt.language", "pt"))
            except STTError as err:
                print(f"  {name}: ERRO {err}")
                break
            print(f"  {name} (volta {rnd}): {time.time() - t0:5.2f}s  → «{text}»")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())