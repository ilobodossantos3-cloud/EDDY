from collections import Counter
from pathlib import Path


def run(ctx, user_input=""):
    v = ctx.vault
    v.build_index(force=True)
    g = v.graph()
    titles = Counter(Path(n).stem.lower() for n in g["nodes"])
    dups = [t for t, c in titles.items() if c > 1]
    v.save_index()
    lines = [f"- Notas: {len(g['nodes'])}", f"- Ligações: {len(g['edges'])}",
             f"- Notas órfãs: {len(g['orphans'])}" + (f" ({', '.join(g['orphans'][:4])})" if g["orphans"] else ""),
             f"- Ligações partidas: {len(g['broken'])}" + (f" (ex.: {g['broken'][0][0]} → [[{g['broken'][0][1]}]])" if g["broken"] else ""),
             f"- Títulos duplicados: {', '.join(dups) if dups else 'nenhum'}"]
    return "RELATÓRIO DO VAULT:\n" + "\n".join(lines)
