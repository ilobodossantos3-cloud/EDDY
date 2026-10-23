"""Sistema: hora, estado, volume, média, bloqueio, desligar, lembretes."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta

from .registry import ActionResult, Ctx, action, obj

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    # sempre lista de argumentos, nunca shell=True
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


@action("time_now", "Diz a hora e a data atuais.", obj(), risk=0, family="sistema")
def time_now(ctx: Ctx) -> ActionResult:
    now = datetime.now()
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    return ActionResult(True, f"São {now:%H:%M} de {dias[now.weekday()]}, {now:%d/%m/%Y}.")


@action("system_status", "Estado do PC: CPU, RAM, disco, bateria e processos mais pesados.", obj(), risk=0, family="sistema")
def system_status(ctx: Ctx) -> ActionResult:
    import psutil
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    disk = shutil.disk_usage(".")
    parts = [f"CPU a {cpu:.0f}%", f"RAM a {ram.percent:.0f}%", f"disco com {disk.free / 1e9:.0f} GB livres"]
    try:
        bat = psutil.sensors_battery()
        if bat:
            parts.append(f"bateria a {bat.percent:.0f}%{' a carregar' if bat.power_plugged else ''}")
    except Exception:
        pass
    procs = []
    for p in psutil.process_iter(["name", "memory_percent"]):
        try:
            procs.append((p.info["memory_percent"] or 0, p.info["name"] or "?"))
        except Exception:
            continue
    top = sorted(procs, reverse=True)[:3]
    parts.append("mais pesados: " + ", ".join(f"{n} ({m:.0f}%)" for m, n in top))
    return ActionResult(True, "; ".join(parts) + ".", {"cpu": cpu, "ram": ram.percent})


# ---------------- volume ----------------
def _win_volume():
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL  # type: ignore
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):          # pycaw recente
        return dev.EndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def set_volume_percent(pct: int) -> bool:
    pct = max(0, min(100, int(pct)))
    if IS_WIN:
        try:
            _win_volume().SetMasterVolumeLevelScalar(pct / 100.0, None)
            return True
        except Exception:
            return False
    if IS_MAC:
        return _run(["osascript", "-e", f"set volume output volume {pct}"]).returncode == 0
    if shutil.which("pactl"):
        return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"]).returncode == 0
    if shutil.which("amixer"):
        return _run(["amixer", "sset", "Master", f"{pct}%"]).returncode == 0
    return False


def get_volume_percent() -> int | None:
    if IS_WIN:
        try:
            return round(_win_volume().GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None
    if IS_MAC:
        r = _run(["osascript", "-e", "output volume of (get volume settings)"])
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None
    if shutil.which("pactl"):
        m = re.search(r"(\d+)%", _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]).stdout)
        return int(m.group(1)) if m else None
    return None


@action("volume_set", "Define o volume do PC (0 a 100).",
        obj({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["percent"]), risk=1, family="som",
        summarize=lambda a: f"volume para {a.get('percent')}%")
def volume_set(ctx: Ctx, percent: int) -> ActionResult:
    if set_volume_percent(percent):
        return ActionResult(True, f"Volume a {percent}%.")
    return ActionResult(False, "Não consegui mexer no volume (no Windows precisa do pacote 'pycaw').")


@action("volume_change", "Aumenta ou diminui o volume em pontos percentuais (positivo ou negativo).",
        obj({"delta": {"type": "integer", "minimum": -100, "maximum": 100}}, ["delta"]), risk=1, family="som",
        summarize=lambda a: f"volume {a.get('delta'):+d} pontos")
def volume_change(ctx: Ctx, delta: int) -> ActionResult:
    cur = get_volume_percent()
    if cur is None:
        return ActionResult(False, "Não consegui ler o volume atual.")
    new = max(0, min(100, cur + delta))
    return volume_set(ctx, new)


@action("volume_get", "Diz o volume atual.", obj(), risk=0, family="som")
def volume_get(ctx: Ctx) -> ActionResult:
    v = get_volume_percent()
    return ActionResult(v is not None, f"O volume está a {v}%." if v is not None else "Não consegui ler o volume.")


_MEDIA = {"playpause": "playpause", "next": "nexttrack", "previous": "prevtrack", "mute": "volumemute"}


@action("media_key", "Tecla multimédia: playpause, next, previous ou mute.",
        obj({"key": {"type": "string", "enum": list(_MEDIA)}}, ["key"]), risk=1, family="som",
        summarize=lambda a: f"tecla multimédia {a.get('key')}")
def media_key(ctx: Ctx, key: str) -> ActionResult:
    try:
        import pyautogui  # type: ignore
        pyautogui.FAILSAFE = True
        pyautogui.press(_MEDIA[key])
    except ImportError:
        return ActionResult(False, "Falta o pacote 'pyautogui' (pip install -r requirements-control.txt).")
    except Exception as e:
        return ActionResult(False, f"Não consegui enviar a tecla ({type(e).__name__}).")
    return ActionResult(True, "Feito.")


@action("lock_screen", "Bloqueia a sessão do PC.", obj(), risk=2, family="sistema")
def lock_screen(ctx: Ctx) -> ActionResult:
    if IS_WIN:
        r = _run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif IS_MAC:
        r = _run(["pmset", "displaysleepnow"])
    else:
        r = _run(["loginctl", "lock-session"])
    return ActionResult(r.returncode == 0, "Ecrã bloqueado." if r.returncode == 0 else "Não consegui bloquear.")


@action("power", "Desliga ou reinicia o PC (arranca em 30 segundos; pode ser cancelado).",
        obj({"mode": {"type": "string", "enum": ["shutdown", "restart"]}}, ["mode"]), risk=3, family="sistema",
        summarize=lambda a: f"{'DESLIGAR' if a.get('mode') == 'shutdown' else 'REINICIAR'} o PC em 30 segundos")
def power(ctx: Ctx, mode: str) -> ActionResult:
    if IS_WIN:
        cmd = ["shutdown", "/s" if mode == "shutdown" else "/r", "/t", "30"]
    else:
        cmd = ["shutdown", "-h" if mode == "shutdown" else "-r", "+1"]
    r = _run(cmd)
    return ActionResult(r.returncode == 0, "Em 30 segundos. Diz 'cancela o desligar' se te enganaste."
                        if r.returncode == 0 else "Não consegui agendar.")


@action("power_cancel", "Cancela um desligar/reiniciar agendado.", obj(), risk=1, family="sistema")
def power_cancel(ctx: Ctx) -> ActionResult:
    r = _run(["shutdown", "/a"] if IS_WIN else ["shutdown", "-c"])
    return ActionResult(r.returncode == 0, "Cancelado." if r.returncode == 0 else "Não havia nada para cancelar.")


# ---------------- lembretes ----------------
@action("remind", "Cria um lembrete: em X minutos ('in_minutes') ou a uma hora 'HH:MM' ('at').",
        obj({"text": {"type": "string", "maxLength": 200},
             "in_minutes": {"type": "number", "minimum": 0.1, "maximum": 10080},
             "at": {"type": "string", "pattern": r"^\d{1,2}:\d{2}$"}}, ["text"]), risk=1, family="lembretes",
        summarize=lambda a: f"lembrete '{a.get('text')}'")
def remind(ctx: Ctx, text: str, in_minutes: float | None = None, at: str | None = None) -> ActionResult:
    if ctx.reminders is None:
        return ActionResult(False, "Os lembretes não estão ativos.")
    now = datetime.now()
    if in_minutes is not None:
        when = now + timedelta(minutes=in_minutes)
    elif at:
        h, m = (int(x) for x in at.split(":"))
        if not (0 <= h < 24 and 0 <= m < 60):
            return ActionResult(False, "Hora inválida.")
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
    else:
        return ActionResult(False, "Diz-me quando: em quantos minutos ou a que horas.")
    ctx.reminders.add(when.timestamp(), text)
    return ActionResult(True, f"Lembrete marcado para as {when:%H:%M}.")


@action("reminders_list", "Lista os lembretes pendentes.", obj(), risk=0, family="lembretes")
def reminders_list(ctx: Ctx) -> ActionResult:
    items = ctx.reminders.list() if ctx.reminders else []
    if not items:
        return ActionResult(True, "Não tens lembretes pendentes.")
    txt = "; ".join(f"{datetime.fromtimestamp(i['ts']):%H:%M} {i['text']}" for i in items[:6])
    return ActionResult(True, f"Tens {len(items)}: {txt}.", {"items": items})
