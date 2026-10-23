"""Botão de pânico: atalho global (se possível), frase de voz e API."""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("eddy.panic")


class KillSwitch:
    def __init__(self, hotkey: str, on_panic: Callable[[], None]):
        self.hotkey = hotkey
        self.on_panic = on_panic
        self._hooked = False

    def install(self) -> bool:
        """Regista o atalho global. Devolve False se a lib 'keyboard' não existir ou não for permitido."""
        try:
            import keyboard  # type: ignore
            keyboard.add_hotkey(self.hotkey, lambda: threading.Thread(target=self.on_panic, daemon=True).start())
            self._hooked = True
        except Exception as e:  # ImportError, permissões, Linux sem root...
            log.info("Atalho de pânico global indisponível (%s). O botão do HUD e a voz continuam a funcionar.", e)
        return self._hooked
