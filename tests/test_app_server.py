import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import FakeProvider, auto_confirm, tc
from eddy.server.app import create_app

TOKEN = "tok-123"


def test_matcher_path_runs_without_llm(make_eddy):
    p = FakeProvider([])
    e = make_eddy(p, dry_run=True)
    r = e.handle_text("abre o chrome", speak=False)
    assert p.calls == [] and r                     # nenhum pedido ao LLM
    assert any(x.get("action") == "app_open" for x in e.audit.tail(10))


def test_unmatched_goes_to_llm_and_logs_to_vault(make_eddy):
    p = FakeProvider(["Paris, claro."])
    e = make_eddy(p)
    assert e.handle_text("qual é a capital de França?", speak=False) == "Paris, claro."
    import time as t
    assert "capital de França" in e.vault.read(f"raw/{t.strftime('%Y-%m-%d')}.md")


def test_llm_error_is_spoken_not_raised(make_eddy):
    from eddy.llm.base import LLMError
    class Boom(FakeProvider):
        def chat(self, *a, **k): raise LLMError("Sem ligação ao modelo.")
    e = make_eddy(Boom([]))
    assert "Sem ligação" in e.handle_text("conta-me uma piada", speak=False)


def test_panic_and_private_and_sarcasm(make_eddy):
    e = make_eddy()
    e.handle_text("para tudo", speak=False)
    assert e.session.panic
    assert not e.executor.execute("files_create_folder", {"path": "x"}).ok
    e.handle_text("retoma as ações", speak=False)
    assert not e.session.panic
    e.handle_text("menos sarcasmo", speak=False)
    assert e.cfg.get("personality.sarcasm") == 1
    e.handle_text("sarcasmo 3", speak=False)
    assert e.cfg.get("personality.sarcasm") == 3
    e.handle_text("modo privado", speak=False)
    assert e.cfg.get("voice.tts.private_mode") is True


def test_shutdown_by_voice_needs_confirmation(make_eddy, monkeypatch):
    import eddy.actions.system as system
    ran = []
    monkeypatch.setattr(system, "_run", lambda cmd, timeout=10: ran.append(cmd) or type("R", (), {"returncode": 0})())
    e = make_eddy()
    r = e.handle_text("desliga o pc", speak=False)         # ninguém confirma
    assert ran == [] and "confirmado" in r.lower()
    auto_confirm(e, True)
    e.handle_text("desliga o pc", speak=False)
    assert ran and ran[0][0] == "shutdown"


def test_voice_confirmation_needs_code(make_eddy, monkeypatch):
    import eddy.actions.system as system
    ran = []
    monkeypatch.setattr(system, "_run", lambda cmd, timeout=10: ran.append(cmd) or type("R", (), {"returncode": 0})())
    e = make_eddy()
    codes = {}
    e.subscribe(lambda k, d: codes.update(d) if k == "confirm_request" else None)
    import threading
    th = threading.Thread(target=lambda: e.handle_text("desliga o pc", speak=False))
    th.start()
    while "code" not in codes:
        time.sleep(0.01)
    e.handle_text("sim confirma", speak=False)            # sem código: ignorado
    assert th.is_alive() and not ran
    e.handle_text(f"confirma {codes['code']}", speak=False)
    th.join(timeout=3)
    assert ran


def test_slash_commands(make_eddy):
    e = make_eddy()
    assert "Perfis" in e.handle_text("/modelo", speak=False)
    assert "Ações" in e.handle_text("/acoes", speak=False)
    assert "desconhecido" in e.handle_text("/xpto", speak=False)
    assert e.handle_text("/seguro", speak=False) and e.session.mode == "safe"


def test_hud_state_shape(make_eddy):
    e = make_eddy()
    h = e.hud_state()
    for k in ("llm", "voice", "mode", "briefing", "skills", "actions", "notes", "state"):
        assert k in h
    json.dumps(h, default=str)


def test_audit_summary(make_eddy):
    e = make_eddy()
    e.handle_text("que horas são", speak=False)
    assert "ações" in e.handle_text("o que fizeste hoje?", speak=False)


def test_switch_model_unknown(make_eddy):
    e = make_eddy()
    assert "Não encontrei" in e.switch_model("xyz")


# ---------------- servidor ----------------
@pytest.fixture
def client(make_eddy):
    e = make_eddy(FakeProvider(["Resposta de teste."]))
    app = create_app(e, TOKEN, 8765)
    return e, TestClient(app, base_url="http://127.0.0.1:8765")


def test_http_basics_and_headers(client):
    e, c = client
    r = c.get("/")
    assert r.status_code == 200 and "EDDY" in r.text and "{{THEME}}" not in r.text and "eddy-cyan" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert c.get("/healthz").json()["ok"] is True
    assert c.get("/static/hud.js").status_code == 200
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    assert c.get("/static/../config.yaml").status_code in (404, 400)


def test_host_header_rejected(client):
    e, c = client
    r = c.get("/", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_ws_rejects_bad_token_and_origin(client):
    e, c = client
    with pytest.raises(WebSocketDisconnect):
        with WS(c, "/ws?t=errado"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with WS(c, f"/ws?t={TOKEN}", origin="https://evil.example.com"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with WS(c, "/ws"):
            pass


def WS(c, path, **headers):
    return c.websocket_connect(path, headers={"host": "127.0.0.1:8765", **headers})


def recv_until(ws, kind, n=30):
    for _ in range(n):
        m = json.loads(ws.receive_text())
        if m["type"] == kind:
            return m
    raise AssertionError(f"não chegou {kind}")


def test_ws_text_roundtrip(client):
    e, c = client
    with WS(c, f"/ws?t={TOKEN}", origin="http://127.0.0.1:8765") as ws:
        assert recv_until(ws, "hud")["data"]["mode"] == "NORMAL"
        ws.send_text(json.dumps({"type": "text", "text": "qual é a capital de França?"}))
        assert recv_until(ws, "reply")["data"]["text"] == "Resposta de teste."


def test_ws_confirm_flow_from_hud(client, monkeypatch):
    e, c = client
    import eddy.actions.system as system
    ran = []
    monkeypatch.setattr(system, "_run", lambda cmd, timeout=10: ran.append(cmd) or type("R", (), {"returncode": 0})())
    with WS(c, f"/ws?t={TOKEN}") as ws:
        ws.send_text(json.dumps({"type": "text", "text": "desliga o pc"}))
        req = recv_until(ws, "confirm_request")
        assert req["data"]["level"] == 3 and "DESLIGAR" in req["data"]["summary"]
        ws.send_text(json.dumps({"type": "confirm", "id": req["data"]["id"], "accept": True}))
        recv_until(ws, "confirm_done")
    time.sleep(0.2)
    assert ran


def test_ws_ignores_garbage_and_oversize(client):
    e, c = client
    with WS(c, f"/ws?t={TOKEN}") as ws:
        ws.send_text("não é json")
        ws.send_text("x" * 10000)
        ws.send_text(json.dumps({"type": "confirm", "id": 123}))
        ws.send_text(json.dumps({"type": "tipo_inventado"}))
        ws.send_text(json.dumps({"type": "panic"}))
        assert recv_until(ws, "panic")


def test_ws_cannot_confirm_unknown_or_replay(client):
    e, c = client
    assert not e.confirm.resolve("inexistente", True, "hud")


def test_hud_assets_have_no_external_urls():
    from pathlib import Path
    import re
    d = Path(__file__).resolve().parent.parent / "eddy" / "hud_web"
    for f in list(d.glob("*.*")) + list((d / "themes").glob("*.css")):
        txt = f.read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=[\"']https?://|url\(https?://|@import", txt), f.name
