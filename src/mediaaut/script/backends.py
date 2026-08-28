"""Moteurs d'ecriture interchangeables.

Trois voies, choisies par `SCRIPT_BACKEND` dans `.env` :

- **ollama** — modele local, cout nul, tourne sur le GPU de la machine.
  C'est le defaut : le projet doit pouvoir fonctionner sans depense tant
  qu'il ne rapporte rien.
- **anthropic** — meilleure ecriture, quelques centimes par script.
- **manual** — lit des scripts deja rediges deposes dans `data/scripts/`.
  Utile quand on veut ecrire soi-meme, ou faire ecrire ailleurs, sans
  renoncer au reste du pipeline.

Les trois rendent le meme objet valide par Pydantic, donc le pipeline en
aval ne sait pas lequel a servi.
"""

from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

ANTHROPIC_MODEL = "claude-opus-5"


def _ollama(system: str, instruction: str, schema: type[T]) -> T:
    """Genere avec un modele local servi par Ollama.

    Le schema JSON est transmis via `format`, ce qui contraint le decodage
    et evite d'avoir a rattraper du JSON approximatif. `think: false`
    desactive le raisonnement des modeles qui en emettent : sans cela leur
    trace se retrouve melangee a la reponse.
    """
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": instruction},
                ],
                "format": schema.model_json_schema(),
                "think": False,
                "stream": False,
                "options": {"temperature": 0.85, "num_ctx": 8192},
            },
            timeout=600,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama injoignable sur {settings.ollama_host} — le service est-il demarre ? ({exc})"
        ) from exc

    if response.status_code != 200:
        raise RuntimeError(f"Ollama a repondu {response.status_code} : {response.text[:200]}")

    content = response.json().get("message", {}).get("content", "")
    try:
        return schema.model_validate_json(content)
    except ValidationError as exc:
        raise RuntimeError(
            f"sortie du modele local non conforme au schema : {exc.errors()[:2]}"
        ) from exc


def _anthropic(system: str, instruction: str, schema: type[T]) -> T:
    """Genere via l'API Anthropic, avec sortie structuree validee."""
    import anthropic

    client = anthropic.Anthropic(api_key=get_settings().require("anthropic_api_key"))
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=system,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": instruction}],
        output_format=schema,
    )
    return response.parsed_output


def generate(system: str, instruction: str, schema: type[T]) -> T:
    """Point d'entree unique : dispatche vers le backend configure."""
    backend = get_settings().script_backend
    if backend == "ollama":
        return _ollama(system, instruction, schema)
    if backend == "anthropic":
        return _anthropic(system, instruction, schema)
    raise RuntimeError(
        f"le backend « {backend} » n'ecrit pas de lui-meme ; "
        "deposer les scripts dans data/scripts/ et utiliser `mediaaut scripts import`"
    )


def check_backend() -> tuple[bool, str]:
    """Verifie que le backend configure est utilisable, sans rien generer."""
    settings = get_settings()
    backend = settings.script_backend

    if backend == "anthropic":
        return (
            (True, f"anthropic ({ANTHROPIC_MODEL})")
            if settings.anthropic_api_key
            else (False, "ANTHROPIC_API_KEY absent de .env")
        )
    if backend == "manual":
        return True, "manuel — scripts fournis a la main"

    try:
        response = httpx.get(f"{settings.ollama_host}/api/tags", timeout=10)
        models = [m["name"] for m in response.json().get("models", [])]
    except httpx.HTTPError:
        return False, f"Ollama injoignable sur {settings.ollama_host}"

    wanted = settings.ollama_model
    # Ollama suffixe les noms sans etiquette par « :latest ».
    if wanted in models or f"{wanted}:latest" in models:
        return True, f"ollama ({wanted})"
    available = ", ".join(models[:4]) or "aucun"
    return False, f"modele {wanted} absent ; installes : {available}"


def dump_schema(schema: type[BaseModel]) -> str:
    """Schema lisible, utile pour rediger un script a la main."""
    return json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)
