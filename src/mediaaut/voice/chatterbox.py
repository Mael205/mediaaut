"""Chatterbox-Turbo : voix nettement plus naturelle que Kokoro.

Kokoro pese 82 millions de parametres — dimensionne pour tourner partout,
au prix d'une diction reconnaissable comme synthetique. Chatterbox-Turbo
est d'un autre ordre : dans une etude d'ecoute a l'aveugle, 65 % des
auditeurs l'ont prefere a ElevenLabs contre 25 % l'inverse. Licence MIT,
execution locale, et clonage de voix a partir de dix secondes d'audio.

Le modele vit dans `.venv-tts`, un environnement separe : ses versions
epinglees de torch, transformers et numpy sont incompatibles avec celles
dont dependent Whisper et onnxruntime. On lui parle par un processus
persistant, ce qui evite de recharger le modele a chaque phrase.
"""

from __future__ import annotations

import atexit
import json
import subprocess
import sys
from pathlib import Path

from mediaaut.core.logging import get_logger
from mediaaut.core.paths import ASSETS, ROOT
from mediaaut.voice.base import VoiceResult

log = get_logger(__name__)

TTS_VENV = ROOT / ".venv-tts"
WORKER = ROOT / "scripts" / "chatterbox_worker.py"
# Echantillons de voix a cloner, deposes par l'utilisateur. Dix secondes de
# parole propre suffisent ; au-dela le clonage ne s'ameliore plus.
VOICE_SAMPLES = ASSETS / "voices"

# Le premier appel telecharge les poids et compile les noyaux CUDA.
_FIRST_CALL_TIMEOUT = 900
_CALL_TIMEOUT = 300


def _python() -> Path:
    exe = TTS_VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not exe.exists():
        raise RuntimeError(
            f"environnement TTS absent : {TTS_VENV}\n"
            f"Le creer avec :\n"
            f"  py -m venv .venv-tts\n"
            f"  .venv-tts\\Scripts\\python -m pip install torch==2.6.0 torchaudio==2.6.0 "
            f"--index-url https://download.pytorch.org/whl/cu124\n"
            f"  .venv-tts\\Scripts\\python -m pip install chatterbox-tts"
        )
    return exe


class ChatterboxVoice:
    name = "chatterbox"

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._first_call = True

    def _worker(self) -> subprocess.Popen:
        """Demarre le processus de synthese, ou reutilise celui en cours."""
        if self._process is not None and self._process.poll() is None:
            return self._process

        log.info("demarrage du moteur Chatterbox")
        self._process = subprocess.Popen(
            [str(_python()), str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # stderr laisse ouvert vers la console : le telechargement des
            # poids prend plusieurs minutes au premier appel, et sans sa
            # progression l'utilisateur croit a un blocage.
            stderr=None,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )
        atexit.register(self.close)
        return self._process

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _sample_for(self, voice_id: str) -> str | None:
        """Chemin de l'echantillon a cloner, s'il en existe un.

        `voice_id` designe un fichier de `data/assets/voices/`. Sans
        echantillon, Chatterbox utilise sa voix par defaut — deja bien
        au-dessus de Kokoro, mais identique d'une chaine a l'autre.
        """
        if not voice_id or voice_id == "default":
            return None
        for suffix in (".wav", ".mp3", ".flac", ".m4a"):
            candidate = VOICE_SAMPLES / f"{voice_id}{suffix}"
            if candidate.exists():
                return str(candidate.resolve())
        log.warning(
            "aucun echantillon « %s » dans %s, voix par defaut utilisee",
            voice_id, VOICE_SAMPLES,
        )
        return None

    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice_id: str = "default",
        speed: float = 1.0,
        lang: str = "en",
    ) -> VoiceResult:
        if not text.strip():
            raise ValueError("texte vide passe a la synthese vocale")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        worker = self._worker()
        request = {
            "text": text,
            "out_path": str(out_path.resolve()),
            "device": "cuda",
            "voice_sample": self._sample_for(voice_id),
        }

        try:
            worker.stdin.write(json.dumps(request) + "\n")
            worker.stdin.flush()
            line = worker.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            self.close()
            raise RuntimeError(f"le moteur Chatterbox s'est arrete : {exc}") from exc

        if not line:
            self.close()
            raise RuntimeError("le moteur Chatterbox n'a rien repondu")

        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(
                f"synthese echouee : {response.get('error', 'sans detail')}"
            )

        self._first_call = False
        result = VoiceResult(
            path=out_path,
            duration=response["duration"],
            sample_rate=response["sample_rate"],
            voice_id=voice_id,
            provider=self.name,
        )
        log.info("voix generee : %.1fs, voix=%s", result.duration, voice_id)
        return result

    def list_voices(self, lang: str | None = None) -> list[str]:
        """Echantillons disponibles pour le clonage.

        Contrairement a Kokoro, Chatterbox n'a pas de catalogue de voix : il
        clone celle qu'on lui donne. La liste est donc celle des fichiers
        deposes dans `data/assets/voices/`.
        """
        if not VOICE_SAMPLES.exists():
            return ["default"]
        found = sorted(
            p.stem for p in VOICE_SAMPLES.iterdir()
            if p.suffix.lower() in (".wav", ".mp3", ".flac", ".m4a")
        )
        return ["default", *found]
