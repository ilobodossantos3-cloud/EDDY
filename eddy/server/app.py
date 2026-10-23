"""Servidor local do HUD: FastAPI + WebSocket. Só aceita localhost + token aleatório."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

log = logging.getLogger("eddy.server")
HUD_DIR = Path(__file__).resolve().parent.parent / "hud_web"
MAX_MSG = 4000
SKILL_CMDS = {"metricas": "metricas", "caixa-de-entrada": "caixa", "tendencias": "tendencias",
              "plano-de-hoje": "plano", "vault": "vault"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _origin_ok(origin: str | None, port: int) -> bool:
    if not origin:          # clientes que não são browsers (testes, pywebview em alguns SO)
        return True
    u = urlparse(origin)
    return u.hostname in ("127.0.0.1", "localhost") and (u.port in (None, port))


def create_app(eddy, token: str, port: int = 8765) -> FastAPI:
    app = FastAPI(title="Eddy HUD", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    theme = str(eddy.cfg.get("hud.theme", "eddy-cyan"))
    if not (HUD_DIR / "themes" / f"{theme}.css").exists():
        theme = "eddy-cyan"

    @app.middleware("http")
    async def sec_headers(request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'; base-uri 'none'")
        return resp

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html = (HUD_DIR / "index.html").read_text(encoding="utf-8").replace("{{THEME}}", theme)
        return HTMLResponse(html)

    @app.get("/healthz")
    async def health():
        return JSONResponse({"ok": True, "state": eddy.state})

    app.mount("/static", StaticFiles(directory=str(HUD_DIR)), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if not secrets.compare_digest(ws.query_params.get("t", ""), token) or not _origin_ok(ws.headers.get("origin"), port):
            await ws.close(code=4403)
            return
        await ws.accept()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        last_level = [0.0]

        def on_event(type_: str, data: dict) -> None:
            if type_ == "audio_level":
                now = time.time()
                if now - last_level[0] < 0.05:
                    return
                last_level[0] = now

            def put():
                try:
                    q.put_nowait({"type": type_, "data": data})
                except asyncio.QueueFull:
                    pass
            loop.call_soon_threadsafe(put)

        eddy.subscribe(on_event)

        async def sender():
            while True:
                msg = await q.get()
                await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))

        send_task = asyncio.create_task(sender())
        try:
            await ws.send_text(json.dumps({"type": "hud", "data": eddy.hud_state()}, ensure_ascii=False, default=str))
            await ws.send_text(json.dumps({"type": "state", "data": {"state": eddy.state}}))
            for ev in list(eddy.events)[-15:]:
                if ev["type"] in ("reply", "transcript", "action_done"):
                    await ws.send_text(json.dumps({"type": ev["type"], "data": ev["data"], "replay": True}, ensure_ascii=False, default=str))
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_MSG:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    await _handle(eddy, loop, msg)
        except WebSocketDisconnect:
            pass
        finally:
            eddy.unsubscribe(on_event)
            send_task.cancel()

    return app


async def _handle(eddy, loop, msg: dict) -> None:
    t = msg.get("type")
    run = lambda fn, *a: asyncio.ensure_future(loop.run_in_executor(None, fn, *a))  # noqa: E731
    if t == "text" and isinstance(msg.get("text"), str):
        run(eddy.handle_text, msg["text"][:1000], "text")
    elif t == "ptt_down":
        run(eddy.ptt_down)
    elif t == "ptt_up":
        run(eddy.ptt_up)
    elif t == "confirm" and isinstance(msg.get("id"), str):
        # Só o HUD (teclado/rato do utilizador) pode confirmar por esta via.
        eddy.confirm.resolve(msg["id"], bool(msg.get("accept")), source="hud")
    elif t == "panic":
        run(eddy.panic)
    elif t == "clear_panic":
        eddy.executor.clear_panic()
        eddy.emit("hud", eddy.hud_state())
    elif t == "private":
        eddy.set_private(bool(msg.get("on")))
    elif t == "skill" and isinstance(msg.get("name"), str):
        cmd = SKILL_CMDS.get(msg["name"])
        if cmd:
            run(eddy.handle_text, "/" + cmd, "text")
    elif t == "hello":
        eddy.emit("hud", eddy.hud_state())
