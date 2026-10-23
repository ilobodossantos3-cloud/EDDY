"""Agendamento (APScheduler): resumo da manhã, plano, métricas, encerrar o dia."""
from __future__ import annotations

import logging

log = logging.getLogger("eddy.scheduler")


def start_scheduler(eddy):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    tz = eddy.cfg.get("user.timezone", "Europe/Lisbon")
    sch = BackgroundScheduler(timezone=tz)
    speak = bool(eddy.cfg.get("scheduler.speak", True))
    for job in eddy.cfg.get("scheduler.jobs", []) or []:
        skill = job.get("skill")
        if not skill or eddy.skills.get(skill) is None:
            log.warning("Tarefa '%s' ignorada: habilidade inexistente.", job.get("name"))
            continue
        try:
            trig = CronTrigger.from_crontab(job["cron"], timezone=tz)
        except Exception:
            log.warning("Cron inválido em '%s'.", job.get("name"))
            continue
        sch.add_job(eddy.run_scheduled, trig, args=[skill, bool(job.get("speak", speak))], id=job.get("name", skill), replace_existing=True,
                    misfire_grace_time=300, coalesce=True, max_instances=1)
    sch.start()
    return sch
