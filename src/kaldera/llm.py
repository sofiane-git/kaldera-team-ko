"""Client LLM réel, utilisé par le chemin « live » (`graph.py`).

L'API exposée par `AZURE_AI_ENDPOINT` est compatible OpenAI (suffixe `/openai/v1`),
d'où `ChatOpenAI` plutôt que `langchain-azure-ai` (celui-ci cible l'API
azure-ai-inference, incompatible avec cette forme d'endpoint — vérifié à la main).
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_REQUIRED = ("AZURE_AI_ENDPOINT", "AZURE_AI_API_KEY", "AZURE_AI_MODEL")


def _load_dotenv() -> None:
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def available() -> bool:
    """Vrai si les identifiants Azure AI sont présents (env ou `.env`)."""
    _load_dotenv()
    return all(os.environ.get(key) for key in _REQUIRED)


def build_llm():
    """Construit le client de complétion de chat depuis les variables d'environnement."""
    _load_dotenv()
    missing = [key for key in _REQUIRED if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"variables d'environnement manquantes : {', '.join(missing)}")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=os.environ["AZURE_AI_ENDPOINT"],
        api_key=os.environ["AZURE_AI_API_KEY"],
        model=os.environ["AZURE_AI_MODEL"],
    )
