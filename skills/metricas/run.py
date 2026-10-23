import time
from eddy.metrics import latest


def run(ctx, user_input=""):
    data = latest(ctx.vault.root)
    if not data:
        return "SEM DADOS em raw/metricas."
    lines = []
    for k, v in sorted(data.items()):
        d = v["delta"]
        extra = "" if d is None else f" ({d:+g} desde o registo anterior)"
        lines.append(f"- {k}: {v['value']:g}{extra}")
    report = "\n".join(lines)
    ctx.vault.write(f"outputs/metricas-{time.strftime('%Y-%m-%d')}.md",
                    f"# Métricas {time.strftime('%Y-%m-%d')}\n\n{report}\n", mode="overwrite")
    return "MÉTRICAS ATUAIS:\n" + report
