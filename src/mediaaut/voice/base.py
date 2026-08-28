"""Interface commune aux moteurs de synthese vocale.

Le pipeline ne connait que ce protocole. Kokoro (local, Apache 2.0) est le
defaut parce qu'il n'a aucune dependance reseau et ne peut donc pas casser
du jour au lendemain ; edge-tts, qui exploite un service Microsoft non
documente, reste branchable mais n'est jamais sur le chemin critique.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class VoiceResult:
    path: Path
    duration: float
    sample_rate: int
    voice_id: str
    provider: str


@runtime_checkable
class VoiceProvider(Protocol):
    name: str

    def synthesize(
        self, text: str, out_path: Path, *, voice_id: str, speed: float = 1.0, lang: str = "en"
    ) -> VoiceResult: ...

    def list_voices(self, lang: str | None = None) -> list[str]: ...


def get_provider(name: str) -> VoiceProvider:
    """Instancie un moteur par nom. Import paresseux : installer edge-tts
    reste optionnel tant qu'on ne s'en sert pas."""
    if name == "kokoro":
        from mediaaut.voice.kokoro import KokoroVoice

        return KokoroVoice()
    if name == "edge":
        from mediaaut.voice.edge import EdgeVoice

        return EdgeVoice()
    raise ValueError(f"moteur de voix inconnu : {name} (attendu : kokoro, edge)")
