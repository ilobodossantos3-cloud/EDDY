"""Gera config/apps.yaml a partir dos atalhos do Menu Iniciar (Windows). Revê o resultado antes de usar:
só as apps que estiverem nesse ficheiro podem ser abertas pelo Eddy."""
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Este script é para Windows. Edita config/apps.yaml à mão.")
        return 1
    dirs = [Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    apps = {}
    for d in dirs:
        for lnk in d.rglob("*.lnk"):
            name = lnk.stem.lower()
            if any(x in name for x in ("uninstall", "desinstal", "readme", "help", "ajuda", "license")):
                continue
            apps[name] = {"exe": str(lnk), "aliases": []}
    path = ROOT / "config" / "apps.yaml"
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = {**apps, **(existing or {}).get("apps", {})}      # o que já tinhas tem prioridade
    path.write_text("# Allowlist de apps (revê!)\n" + yaml.safe_dump({"apps": merged}, allow_unicode=True, sort_keys=True),
                    encoding="utf-8")
    print(f"{len(merged)} apps em {path}. Apaga as que não queres que o Eddy possa abrir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
