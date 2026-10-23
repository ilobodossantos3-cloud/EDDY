import json
import time
from datetime import datetime

import httpx
import pytest

from eddy.briefing import Briefing, parse_weather

OM = {"current": {"temperature_2m": 18.6, "weather_code": 61},
      "daily": {"temperature_2m_max": [22.2], "temperature_2m_min": [13.4], "precipitation_probability_max": [70]}}


def mk(tmp_cfg, handler):
    return Briefing(tmp_cfg, transport=httpx.MockTransport(handler))


def test_parse_weather():
    w = parse_weather(OM, "Amadora")
    assert (w["temp"], w["min"], w["max"], w["rain"], w["desc"], w["place"]) == (19, 13, 22, 70, "chuva fraca", "Amadora")


def test_fetch_sends_only_coordinates_over_https(tmp_cfg):
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        return httpx.Response(200, json=OM)
    b = mk(tmp_cfg, h)
    assert b.fetch_weather()["temp"] == 19
    assert seen["url"].startswith("https://api.open-meteo.com/") and "latitude=38.7536" in seen["url"]
    assert "authorization" not in seen["headers"]


def test_weather_offline_degrades_gracefully(tmp_cfg):
    def h(req):
        raise httpx.ConnectError("sem rede")
    b = mk(tmp_cfg, h)
    assert b.fetch_weather() is None
    assert Briefing.as_text({"greeting": "Bom dia", "name": "S", "date": "x", "weather": None, "plan": [], "reminders": [],
                             "news": [], "system": {}}).count("indisponível") == 1


def test_weather_can_be_disabled(tmp_cfg):
    tmp_cfg.set("briefing.weather.enabled", False)
    called = []
    b = mk(tmp_cfg, lambda r: called.append(1) or httpx.Response(200, json=OM))
    assert b.fetch_weather() is None and b.weather() is None and not called


def test_weather_does_not_block_and_caches(tmp_cfg):
    calls = []

    def h(req):
        calls.append(1)
        time.sleep(0.3)
        return httpx.Response(200, json=OM)
    b = mk(tmp_cfg, h)
    t0 = time.time()
    assert b.weather() is None                      # 1.ª chamada: devolve já, atualiza em segundo plano
    assert time.time() - t0 < 0.2
    for _ in range(40):
        if b._weather:
            break
        time.sleep(0.05)
    assert b.weather()["temp"] == 19 and len(calls) == 1       # cache: sem novo pedido


def test_greeting_and_date():
    assert Briefing.greeting(datetime(2026, 10, 20, 8)) == "Bom dia"
    assert Briefing.greeting(datetime(2026, 10, 20, 15)) == "Boa tarde"
    assert Briefing.greeting(datetime(2026, 10, 20, 23)) == "Boa noite"
    assert Briefing.date_text(datetime(2026, 10, 20)) == "terça-feira, 20 de outubro"


def test_build_has_plan_reminders_news(make_eddy):
    e = make_eddy()
    day = time.strftime("%Y-%m-%d")
    e.vault.write(f"outputs/plano-{day}.md", "# Plano\n\n1. Estudar\n2. Treinar\n", mode="overwrite")
    e.vault.write(f"outputs/resumo-{day}.md", "# R\n\n- [rss] Novo modelo de IA\n- [rss] falhou x (Erro)\n- [inbox] n1: algo\n", mode="overwrite")
    e.reminders.add(time.time() + 600, "Ligar à mãe")
    b = e.briefing.build(e, with_weather=False)
    assert b["plan"] == ["Estudar", "Treinar"] and b["reminders"][0]["text"] == "Ligar à mãe"
    assert b["news"] == ["Novo modelo de IA", "n1: algo"]           # sem a linha que falhou
    txt = Briefing.as_text(b)
    assert "PRIORIDADES: 1) Estudar" in txt and "Ligar à mãe" in txt and "conteúdo externo" in txt
    json.dumps(e.hud_state()["briefing"], default=str)


def test_briefing_skill_and_taint(make_eddy):
    e = make_eddy()
    e.briefing._weather = parse_weather(OM, "Amadora")
    e.vault.write(f"outputs/resumo-{time.strftime('%Y-%m-%d')}.md", "- [rss] Titulo externo\n", mode="overwrite")
    out = e.skills.run("briefing-do-dia", e.ctx)
    assert "19°C" in out and "Amadora" in out and "Titulo externo" in out and "Instruções" in out
    assert e.session.tainted                                         # notícias externas → dados não confiáveis


def test_briefing_voice_command_routes_to_skill(make_eddy):
    from conftest import FakeProvider
    from eddy.llm.base import LLMResponse, ToolCall
    call = LLMResponse(tool_calls=[ToolCall(id="c1", name="run_skill", arguments={"name": "briefing-do-dia"})])
    p = FakeProvider([call, "Boa noite. Tens duas prioridades."])
    e = make_eddy(p)
    e.briefing._weather = parse_weather(OM)
    assert e.handle_text("dá-me o briefing do dia", speak=False) == "Boa noite. Tens duas prioridades."
    assert any(a.get("action") == "run_skill" for a in e.audit.tail(10))


def test_scheduler_job_speak_override(make_eddy, tmp_cfg):
    from eddy.scheduler import start_scheduler
    tmp_cfg.data["scheduler"] = {"enabled": True, "speak": True, "jobs": [
        {"name": "a", "cron": "55 6 * * *", "skill": "caixa-de-entrada", "speak": False},
        {"name": "b", "cron": "0 7 * * *", "skill": "briefing-do-dia"}]}
    e = make_eddy()
    sch = start_scheduler(e)
    try:
        jobs = {j.id: j for j in sch.get_jobs()}
        assert list(jobs["a"].args) == ["caixa-de-entrada", False] and list(jobs["b"].args) == ["briefing-do-dia", True]
        e._scheduler = sch
        assert [j["name"] for j in e.briefing.build(e, False)["jobs"]]
    finally:
        sch.shutdown(wait=False)
