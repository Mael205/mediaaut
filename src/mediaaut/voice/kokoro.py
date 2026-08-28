"""Kokoro-82M via ONNX Runtime : synthese vocale 100% locale.

Choisi comme moteur par defaut pour sa durabilite : poids Apache 2.0
telecharges une fois, inference hors-ligne, aucun service tiers a la merci
d'un changement d'API.

Note : `Kokoro.create_timed` existe mais ne rend jamais de timings avec les
poids publies, dont le graphe ONNX n'a qu'une sortie `audio` et aucune
sortie de duree. Le calage des sous-titres passe donc par Whisper
(cf. mediaaut.subtitles.transcribe), qui sert de toute facon au pipeline
de decoupage.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import soundfile as sf

from mediaaut.core.logging import get_logger
from mediaaut.core.net import download
from mediaaut.core.paths import MODELS
from mediaaut.voice.base import VoiceResult

log = get_logger(__name__)

_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_MODEL_FILE = "kokoro-v1.0.onnx"      # fp32 : le plus rapide sur CPU
_VOICES_FILE = "voices-v1.0.bin"

# Kokoro attend un code BCP-47 ; le reste du projet manipule des codes courts.
_LANG_MAP = {
    "en": "en-us", "en-us": "en-us", "en-gb": "en-gb",
    "fr": "fr-fr", "es": "es", "it": "it", "pt": "pt-br",
    "hi": "hi", "ja": "ja", "zh": "cmn",
}

# Prefixe de voix -> langue. `af_` = american female, `ff_` = french female.
_VOICE_PREFIXES = {
    "en": ("af_", "am_", "bf_", "bm_"), "fr": ("ff_", "fm_"),
    "es": ("ef_", "em_"), "it": ("if_", "im_"), "pt": ("pf_", "pm_"),
    "hi": ("hf_", "hm_"), "ja": ("jf_", "jm_"), "zh": ("zf_", "zm_"),
}


@lru_cache(maxsize=1)
def _load():
    """Charge le modele une seule fois par processus (~1 s de warmup)."""
    from kokoro_onnx import Kokoro

    model = download(_RELEASE + _MODEL_FILE, MODELS / _MODEL_FILE)
    voices = download(_RELEASE + _VOICES_FILE, MODELS / _VOICES_FILE)
    log.info("chargement du modele Kokoro")
    # Kokoro avertit que ses timings phonemes ne s'alignent pas sur les mots.
    # On ne s'en sert pas (cf. docstring du module), le message est du bruit.
    logging.getLogger("kokoro_onnx").setLevel(logging.ERROR)
    return Kokoro(str(model), str(voices))


class KokoroVoice:
    name = "kokoro"

    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice_id: str = "am_michael",
        speed: float = 1.0,
        lang: str = "en",
    ) -> VoiceResult:
        if not text.strip():
            raise ValueError("texte vide passe a la synthese vocale")

        kokoro = _load()
        samples, sample_rate = kokoro.create(
            text, voice=voice_id, speed=speed, lang=_LANG_MAP.get(lang.lower(), lang.lower())
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), samples, sample_rate)

        result = VoiceResult(
            path=out_path,
            duration=len(samples) / sample_rate,
            sample_rate=sample_rate,
            voice_id=voice_id,
            provider=self.name,
        )
        log.info("voix generee : %.1fs, voix=%s", result.duration, voice_id)
        return result

    def list_voices(self, lang: str | None = None) -> list[str]:
        voices = sorted(_load().get_voices())
        if not lang:
            return voices
        wanted = _VOICE_PREFIXES.get(lang.lower())
        return [v for v in voices if v.startswith(wanted)] if wanted else voices
