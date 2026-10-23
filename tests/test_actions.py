import os

import pytest

from conftest import auto_confirm
from eddy.actions import REGISTRY, load_builtin_actions

load_builtin_actions()


def run(e, act, /, **args):
    return e.executor.execute(act, args)


@pytest.fixture
def e(make_eddy):
    ed = make_eddy()
    auto_confirm(ed, True)
    return ed


def docs(e):
    from pathlib import Path
    return Path(e.cfg.get("security.allowed_folders")[0])


def test_files_roundtrip_inside_allowed(e):
    d = docs(e)
    (d / "a.txt").write_text("olá")
    assert run(e, "files_create_folder", path=str(d / "pasta")).ok
    assert run(e, "files_move", source=str(d / "a.txt"), destination=str(d / "pasta")).ok
    assert (d / "pasta" / "a.txt").exists()
    assert run(e, "files_rename", path=str(d / "pasta" / "a.txt"), new_name="b.txt").ok
    assert run(e, "files_read_text", path=str(d / "pasta" / "b.txt")).message == "olá"
    assert e.session.tainted      # conteúdo de ficheiros é externo


def test_files_outside_denied(e, tmp_path):
    out = tmp_path / "fora.txt"
    out.write_text("x")
    for name, args in [("files_read_text", {"path": str(out)}), ("files_list", {"folder": str(tmp_path)}),
                       ("files_delete", {"path": str(out)}), ("files_move", {"source": str(out), "destination": str(docs(e))})]:
        r = run(e, name, **args)
        assert not r.ok, name
    assert out.exists()


def test_files_never_overwrite(e):
    d = docs(e)
    (d / "a.txt").write_text("1")
    (d / "b.txt").write_text("2")
    assert not run(e, "files_move", source=str(d / "a.txt"), destination=str(d / "b.txt")).ok
    assert (d / "b.txt").read_text() == "2"
    assert not run(e, "files_rename", path=str(d / "a.txt"), new_name="b.txt").ok
    assert not run(e, "files_rename", path=str(d / "a.txt"), new_name="../x.txt").ok


def test_delete_goes_to_trash(e, monkeypatch):
    import send2trash
    sent = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: sent.append(p))
    d = docs(e)
    (d / "z.txt").write_text("z")
    assert run(e, "files_delete", path=str(d / "z.txt")).ok
    assert sent and sent[0].endswith("z.txt")
    assert not run(e, "files_delete", path=str(d)).ok      # nunca a pasta-raiz


def test_delete_requires_confirmation(make_eddy, monkeypatch):
    import send2trash
    sent = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: sent.append(p))
    e = make_eddy()
    d = docs(e)
    (d / "z.txt").write_text("z")
    auto_confirm(e, False)
    assert not run(e, "files_delete", path=str(d / "z.txt")).ok and not sent


def test_open_blocks_executables(e, monkeypatch):
    d = docs(e)
    (d / "run.exe").write_text("x")
    (d / "run.bat").write_text("x")
    assert not run(e, "files_open", path=str(d / "run.exe")).ok
    assert not run(e, "files_open", path=str(d / "run.bat")).ok


def test_read_only_text_files(e):
    d = docs(e)
    (d / "img.png").write_bytes(b"\x89PNG")
    assert not run(e, "files_read_text", path=str(d / "img.png")).ok


def test_files_search(e):
    d = docs(e)
    (d / "relatorio-final.txt").write_text("x")
    r = run(e, "files_search", query="relatorio")
    assert r.ok and "relatorio-final.txt" in r.message


def test_app_allowlist(e, monkeypatch):
    import eddy.actions.apps as apps
    launched = []
    monkeypatch.setattr(apps, "_launch", lambda exe: launched.append(exe))
    assert run(e, "app_open", name="Google Chrome").ok and launched == ["chrome.exe"]
    r = run(e, "app_open", name="malware")
    assert not r.ok and launched == ["chrome.exe"]
    assert not run(e, "app_open", name="cmd.exe /c calc").ok


def test_web_open_blocks_dangerous_schemes(e, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    assert not run(e, "web_open", url="javascript:alert(1)").ok
    assert not run(e, "web_open", url="file:///etc/passwd").ok
    assert run(e, "web_open", url="example.com").ok and opened == ["https://example.com"]


def test_web_fetch_blocks_ssrf(e):
    for u in ["http://127.0.0.1:9/x", "http://169.254.169.254/", "http://localhost/"]:
        assert not run(e, "web_fetch", url=u).ok


def test_web_fetch_redirect_to_private_blocked(e, monkeypatch):
    import httpx
    import eddy.actions.web as web
    import eddy.security.sanitize as san
    monkeypatch.setattr(web, "check_url", lambda u, allow_private=False: san.check_url(u, allow_private) if "127." in u or "169." in u else u)
    def handler(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    real = httpx.Client
    monkeypatch.setattr(web.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    r = run(e, "web_fetch", url="https://exemplo.pt/")
    assert not r.ok


def test_html_to_text():
    from eddy.actions.web import html_to_text
    assert html_to_text("<html><head><title>x</title><script>evil()</script></head><body><p>Olá <b>mundo</b></p></body></html>") == "Olá mundo"


def test_press_keys_validation(e):
    assert not run(e, "press_keys", combo="ctrl+alt+delete").ok
    assert not run(e, "press_keys", combo="win+r").ok
    assert not run(e, "press_keys", combo="ctrl+;").ok          # fora do padrão do schema


def test_shell_disabled_by_default(e):
    assert "shell_run" not in [t["function"]["name"] for t in e.executor.catalog()]
    assert not run(e, "shell_run", command="git status").ok


def test_shell_allowlist_exact(make_eddy):
    e = make_eddy()
    e.cfg.set("security.shell.enabled", True)
    auto_confirm(e, True)
    assert not run(e, "shell_run", command="git status; rm -rf /").ok
    assert not run(e, "shell_run", command="rm -rf /").ok


def test_reminders(e):
    assert run(e, "remind", text="beber água", in_minutes=1).ok
    assert "beber água" in run(e, "reminders_list").message
    assert not run(e, "remind", text="x").ok          # falta quando


def test_time_and_status(e):
    assert "São" in run(e, "time_now").message
    assert run(e, "system_status").ok


def test_vault_tools_confined(e):
    assert run(e, "vault_write", path="wiki/t.md", content="olá [[Eddy]] password: abc123").ok
    assert "abc123" not in run(e, "vault_read", path="wiki/t.md").message
    assert not run(e, "vault_write", path="../../fora.md", content="x").ok
    assert not run(e, "vault_read", path="/etc/passwd").ok
    assert not run(e, "vault_write", path="wiki/x.exe", content="x").ok


def test_catalog_has_expected_families():
    fams = {s.family for s in REGISTRY.values()}
    for f in ("apps", "som", "ficheiros", "web", "teclado", "rotinas", "memória", "lembretes", "sistema"):
        assert f in fams
    assert all(s.risk in (0, 1, 2, 3) for s in REGISTRY.values())
    # ações destrutivas/externas nunca abaixo do nível 3
    assert REGISTRY["files_delete"].risk == 3 and REGISTRY["power"].risk == 3 and REGISTRY["routine_save"].risk == 3


def test_routines_plan_confirm(make_eddy, tmp_cfg):
    e = make_eddy()
    (tmp_cfg.root / "config" / "routines.yaml").write_text(
        "teste:\n  description: t\n  steps:\n    - {action: time_now, args: {}}\nmix:\n  description: x\n  steps:\n    - {action: time_now, args: {}}\n    - {action: clipboard_set, args: {text: 'oi'}}\n", encoding="utf-8")
    auto_confirm(e, False)
    r = run(e, "routine_run", name="mix")
    assert not r.ok and "cancelada" in r.message
    assert run(e, "routine_run", name="teste").ok          # só nível 0: sem confirmação


def test_routine_save_blocks_dangerous_actions(e):
    r = run(e, "routine_save", name="mau", steps=[{"action": "power", "args": {"mode": "shutdown"}}])
    assert not r.ok
    r = run(e, "routine_save", name="mau2", steps=[{"action": "shell_run", "args": {"command": "x"}}])
    assert not r.ok
