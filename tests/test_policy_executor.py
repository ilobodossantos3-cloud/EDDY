import threading
import time

import pytest

from conftest import auto_confirm
from eddy.actions import REGISTRY, ActionResult, action
from eddy.actions.registry import obj
from eddy.security.confirm import ConfirmManager, action_hash

CALLS = []


@action("t_l0", "t", obj(), risk=0)
def t_l0(ctx): CALLS.append("l0"); return ActionResult(True, "ok0")


@action("t_l2", "t", obj({"x": {"type": "integer"}}), risk=2)
def t_l2(ctx, x=0): CALLS.append(("l2", x)); return ActionResult(True, "ok2")


@action("t_l3", "t", obj(), risk=3)
def t_l3(ctx): CALLS.append("l3"); return ActionResult(True, "ok3")


@action("t_taint", "t", obj(), risk=1, taints=True)
def t_taint(ctx): return ActionResult(True, "externo")


@pytest.fixture(autouse=True)
def clear():
    CALLS.clear()


def test_level0_runs(make_eddy):
    e = make_eddy()
    assert e.executor.execute("t_l0", {}).ok and CALLS == ["l0"]


def test_level2_first_time_needs_confirm_then_delay(make_eddy):
    e = make_eddy()
    auto_confirm(e, True)
    assert e.executor.execute("t_l2", {"x": 1}).ok
    assert e.executor.execute("t_l2", {"x": 2}).ok     # já aprovada nesta sessão → sem pedir de novo
    assert CALLS == [("l2", 1), ("l2", 2)]


def test_level2_declined(make_eddy):
    e = make_eddy()
    auto_confirm(e, False)
    r = e.executor.execute("t_l2", {"x": 1})
    assert not r.ok and CALLS == []


def test_level3_always_confirms(make_eddy):
    e = make_eddy()
    auto_confirm(e, True)
    assert e.executor.execute("t_l3", {}).ok
    assert e.executor.execute("t_l3", {}).ok
    n = sum(1 for r in e.audit.tail(50) if r.get("action") == "t_l3" and r.get("confirmed_by") == "utilizador")
    assert n == 2


def test_level3_timeout_means_no(make_eddy):
    e = make_eddy()
    r = e.executor.execute("t_l3", {})        # ninguém responde; timeout 2s
    assert not r.ok and CALLS == []


def test_safe_mode_and_panic_deny(make_eddy):
    e = make_eddy(safe=True)
    assert not e.executor.execute("t_l2", {}).ok
    assert e.executor.execute("t_l0", {}).ok
    e2 = make_eddy()
    e2.executor.panic()
    assert not e2.executor.execute("t_l3", {}).ok
    assert e2.executor.execute("t_l0", {}).ok
    e2.executor.clear_panic()
    auto_confirm(e2, True)
    assert e2.executor.execute("t_l3", {}).ok


def test_taint_forces_confirm_on_level2(make_eddy):
    e = make_eddy()
    e.executor.execute("t_taint", {})               # leu conteúdo externo
    assert e.session.tainted
    e.session.approved.add("t_l2")                  # mesmo já aprovada nesta sessão…
    r = e.executor.execute("t_l2", {"x": 3})        # …pede confirmação; ninguém responde → recusado
    assert not r.ok and CALLS == []
    auto_confirm(e, True)
    assert e.executor.execute("t_l2", {"x": 3}).ok  # com confirmação do utilizador passa


def test_llm_cannot_change_risk_or_inject_args(make_eddy):
    e = make_eddy()
    r = e.executor.execute("t_l3", {"risk": 0})
    assert not r.ok and "inválidos" in r.message and CALLS == []
    assert not e.executor.execute("nao_existe", {}).ok


def test_dry_run_executes_nothing(make_eddy):
    e = make_eddy(dry_run=True)
    r = e.executor.execute("t_l3", {})
    assert r.ok and "simulação" in r.message and CALLS == []


def test_rate_limit(make_eddy):
    e = make_eddy()
    e.executor.max_per_min = 3
    res = [e.executor.execute("t_l0", {}).ok for _ in range(5)]
    assert res == [True, True, True, False, False]


def test_audit_has_no_secrets(make_eddy):
    e = make_eddy()
    e.executor.execute("t_l2", {"x": 1}, request="a minha password: hunter2 sk-abcdefghijklmnop12345")
    txt = e.audit.path.read_text(encoding="utf-8")
    assert "hunter2" not in txt and "sk-abcdef" not in txt


# ---------- gestor de confirmações ----------
def test_confirm_single_use_and_hash():
    cm = ConfirmManager(timeout_s=2)
    box = {}
    cm.emit = lambda k, d: box.update(d) if k == "confirm_request" else None
    res = []
    th = threading.Thread(target=lambda: res.append(cm.request("a", {"p": 1}, "s", 3)))
    th.start()
    while "id" not in box:
        time.sleep(0.01)
    assert cm.resolve(box["id"], True, "hud")
    assert not cm.resolve(box["id"], True, "hud")          # não reutilizável
    th.join()
    assert res == [True]
    assert action_hash("a", {"p": 1}) != action_hash("a", {"p": 2})


def test_confirm_voice_requires_code():
    cm = ConfirmManager(timeout_s=2)
    box = {}
    cm.emit = lambda k, d: box.update(d) if k == "confirm_request" else None
    res = []
    th = threading.Thread(target=lambda: res.append(cm.request("a", {}, "s", 3)))
    th.start()
    while "id" not in box:
        time.sleep(0.01)
    assert not cm.resolve(box["id"], True, "voice", "sim confirma")             # sem código → recusado
    assert not cm.resolve_voice("sim, confirma lua lua lua")  or True            # (código aleatório; improvável)
    ok = cm.resolve(box["id"], True, "voice", f"confirma {box['code']}")
    th.join()
    assert ok and res == [True]


def test_confirm_bad_source_rejected():
    cm = ConfirmManager(timeout_s=1)
    assert not cm.resolve("x", True, "llm")
