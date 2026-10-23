import time
from pathlib import Path
from eddy.metrics import read_history


def run(ctx, user_input=""):
    hist = read_history(ctx.vault.root)
    lines = []
    if len(hist) >= 2:
        a, b = hist[0], hist[-1]
        for k in sorted(set(a["values"]) & set(b["values"])):
            d = b["values"][k] - a["values"][k]
            pct = (d / a["values"][k] * 100) if a["values"][k] else 0
            lines.append(f"- {k}: {a['values'][k]:g} → {b['values'][k]:g} ({d:+g}, {pct:+.0f}%) entre {a['date']} e {b['date']}")
    else:
        lines.append("- Menos de 2 registos de métricas: ainda não dá para ver tendências.")
    week = time.time() - 7 * 86400
    new = [p for p in ctx.vault.list() if (Path(ctx.vault.root) / p).stat().st_mtime >= week]
    lines.append(f"- Notas criadas/alteradas nos últimos 7 dias: {len(new)}")
    return "TENDÊNCIAS:\n" + "\n".join(lines)
