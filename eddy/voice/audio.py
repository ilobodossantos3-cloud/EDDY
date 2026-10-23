"""Saída de áudio (PCM 16-bit mono) com nível para o HUD e paragem imediata."""
from __future__ import annotations

import threading
from typing import Callable, Iterable

import numpy as np


class AudioError(RuntimeError):
    pass


class AudioOut:
    def __init__(self, on_level: Callable[[float], None] | None = None):
        self.on_level = on_level or (lambda _: None)
        self._stop = threading.Event()
        self._stream = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        """Barge-in: corta já o áudio."""
        self._stop.set()
        with self._lock:
            s = self._stream
        if s is not None:
            try:
                s.abort()
            except Exception:
                pass

    def reset(self) -> None:
        self._stop.clear()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def play(self, sample_rate: int, chunks: Iterable[bytes]) -> bool:
        """Toca blocos PCM int16 mono. Devolve True se terminou, False se foi interrompido."""
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as e:
            raise AudioError("Falta o 'sounddevice' (pip install -r requirements-voice.txt).") from e
        stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16")
        with self._lock:
            self._stream = stream
        stream.start()
        leftover = b""
        try:
            for chunk in chunks:
                if self._stop.is_set():
                    return False
                data = leftover + chunk
                n = len(data) - (len(data) % 2)
                leftover = data[n:]
                if not n:
                    continue
                arr = np.frombuffer(data[:n], dtype=np.int16)
                self.on_level(float(min(1.0, np.sqrt(np.mean((arr.astype(np.float32) / 32768.0) ** 2)) * 4)))
                stream.write(arr.reshape(-1, 1))
            return not self._stop.is_set()
        finally:
            self.on_level(0.0)
            try:
                if self._stop.is_set():
                    stream.abort()
                else:
                    stream.stop()
                stream.close()
            except Exception:
                pass
            with self._lock:
                self._stream = None
