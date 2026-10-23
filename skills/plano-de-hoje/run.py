import re
import time


def run(ctx, user_input=""):
    day = time.strftime("%Y-%m-%d")
    path = f"outputs/plano-{day}.md"
    items = [i.strip(" -•\t") for i in re.split(r"[;\n]", user_input or "") if i.strip(" -•\t")][:3]
    if items:
        body = f"# Plano {day}\n\n" + "\n".join(f"{n}. {t}" for n, t in enumerate(items, 1)) + "\n"
        ctx.vault.write(path, body, mode="overwrite")
        return "PLANO GUARDADO:\n" + body
    try:
        return "PLANO DE HOJE:\n" + ctx.vault.read(path)
    except Exception:
        return "AINDA NÃO HÁ PLANO PARA HOJE."
