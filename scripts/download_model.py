"""Descarrega um modelo do Hugging Face para models/.

Exemplos:
  python scripts/download_model.py --repo bartowski/Llama-3.2-3B-Instruct-GGUF --file Llama-3.2-3B-Instruct-Q4_K_M.gguf
  python scripts/download_model.py --repo Qwen/Qwen2.5-3B-Instruct            (modelo completo, formato transformers)
Modelos privados/gated: põe HF_TOKEN no .env.
Depois aponta o perfil no config.yaml (model_path) e usa:  python -m eddy --profile local_gguf
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="ex.: Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--file", help="ficheiro GGUF específico dentro do repositório")
    ap.add_argument("--dest", default=str(ROOT / "models"))
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError:
        print("Falta o huggingface_hub:  pip install huggingface_hub", file=sys.stderr)
        return 1
    token = os.environ.get("HF_TOKEN") or None
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    if a.file:
        path = hf_hub_download(repo_id=a.repo, filename=a.file, local_dir=str(dest), token=token)
        print(f"\nOK: {path}\nNo config.yaml, perfil local_gguf:  model_path: models/{a.file}")
    else:
        target = dest / a.repo.split("/")[-1]
        path = snapshot_download(repo_id=a.repo, local_dir=str(target), token=token)
        print(f"\nOK: {path}\nNo config.yaml, perfil local_hf:  model_path: models/{target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
