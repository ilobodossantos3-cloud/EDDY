"""Arranque do Eddy:  python -m eddy [--no-voice] [--profile local_gguf] [--hud window|browser|none] [--safe] [--dry-run]"""
from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser


def _free_port(start: int) -> int:
    for p in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("Não encontrei porta livre.")


def _cli_confirm_hook(eddy):
    """No modo terminal, a confirmação é pedida no próprio terminal (teclado do utilizador)."""
    def on_event(kind, data):
        if kind == "confirm_request":
            print(f"\n⚠  CONFIRMAÇÃO (nível {data['level']}): {data['summary']}")
            ans = input("   Confirmar? [s/N] ").strip().lower()
            eddy.confirm.resolve(data["id"], ans in ("s", "sim", "y", "yes"), source="hud")
        elif kind == "reply":
            print(f"EDDY> {data['text']}")
        elif kind == "notice":
            print(f"[aviso] {data['text']}")
    eddy.subscribe(on_event)


_LOCK_SOCK = None


def _single_instance(port: int) -> bool:
    """Impede duas instâncias: guarda uma porta local enquanto o Eddy corre (libertada ao fechar, mesmo se crashar)."""
    global _LOCK_SOCK
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _LOCK_SOCK = s
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eddy", description="Eddy — assistente de voz que controla o PC")
    ap.add_argument("--config", help="caminho para outro config.yaml")
    ap.add_argument("--no-voice", action="store_true", help="sem microfone nem voz (só HUD/terminal)")
    ap.add_argument("--profile", help="perfil de modelo (ex.: inception, nvidia, local_gguf, local_hf)")
    ap.add_argument("--hud", choices=["window", "browser", "none"], help="interface")
    ap.add_argument("--safe", action="store_true", help="modo seguro: só ações de nível 0-1")
    ap.add_argument("--dry-run", action="store_true", help="simulação: mostra o que faria, sem executar")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    from .config import Config
    overrides: dict = {}
    if a.profile:
        overrides["llm"] = {"active": a.profile}
    if a.hud:
        overrides["hud"] = {"mode": a.hud}
    cfg = Config.load(a.config, overrides)
    (cfg.root / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(cfg.root / "logs" / "eddy.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stderr)])
    logging.getLogger("httpx").setLevel(logging.WARNING)   # nunca registar URLs/cabeçalhos
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    if cfg.get("app.single_instance", True) and not _single_instance(int(cfg.get("app.lock_port", 8799))):
        print("O Eddy já está a correr (fecha a outra janela primeiro).", file=sys.stderr)
        return 3

    from .app import Eddy
    from .engine import lines
    eddy = Eddy(cfg, voice=False if a.no_voice else None, safe=a.safe, dry_run=a.dry_run)
    eddy.start()
    mode = cfg.get("hud.mode", "window")
    greet = lambda: eddy.say(lines.pick("startup", eddy._sarcasm()) or "Estou pronto.", cache=True)  # noqa: E731

    if mode == "none":
        _cli_confirm_hook(eddy)
        print("Eddy no terminal. Escreve um pedido (ou /ajuda). Ctrl+C para sair.")
        if not a.no_voice:
            threading.Thread(target=greet, daemon=True).start()
        try:
            while True:
                text = input("TU> ").strip()
                if text:
                    eddy.handle_text(text, source="text", speak=eddy.voice_enabled)
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            eddy.stop()
        return 0

    import uvicorn
    from .server.app import create_app, new_token
    host = "127.0.0.1"                                   # fixo: o HUD nunca fica exposto à rede
    port = _free_port(int(cfg.get("hud.port", 8765)))
    token = new_token()
    app = create_app(eddy, token, port)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", ws_ping_interval=20))
    t = threading.Thread(target=server.run, daemon=True, name="eddy-server")
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://{host}:{port}/?t={token}"
    print(f"Eddy a correr. HUD: {url}")
    threading.Timer(1.5, lambda: threading.Thread(target=greet, daemon=True).start()).start()

    try:
        if mode == "window":
            try:
                import webview  # type: ignore
                webview.create_window("EDDY", url, width=1360, height=840, background_color="#02070d")
                webview.start()
            except ImportError:
                print("(pywebview não instalado: a abrir no browser. Instala com: pip install pywebview)")
                webbrowser.open(url)
                while t.is_alive():
                    time.sleep(0.5)
        else:
            webbrowser.open(url)
            while t.is_alive():
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        eddy.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())