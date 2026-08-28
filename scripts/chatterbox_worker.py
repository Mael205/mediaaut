"""Synthese vocale Chatterbox, executee dans son propre environnement.

Ce script ne tourne PAS dans le venv du projet. Chatterbox epingle
`torch==2.6.0`, `transformers==5.2.0` et `numpy<2`, alors que le projet
utilise numpy 2.5 pour onnxruntime et ctranslate2. Les installer ensemble
retrograderait numpy et casserait Whisper — donc les sous-titres et le
decoupage. Chatterbox vit dans `.venv-tts`, et on lui parle par ce script.

Protocole : une requete JSON sur l'entree standard, une reponse JSON sur la
sortie standard. Le modele reste charge entre deux requetes tant que le
processus vit, ce qui evite de payer les quelques secondes de chargement a
chaque phrase.
"""

from __future__ import annotations

import json
import sys
import traceback

# Les librairies de modeles ecrivent barres de progression et avertissements
# sur la sortie standard. Elle est reservee au protocole JSON : on la met de
# cote des le demarrage et on redirige tout le reste vers stderr, sinon la
# premiere reponse est precedee d'un telechargement et devient illisible.
_CHANNEL = sys.stdout
sys.stdout = sys.stderr

_model = None


def _load(device: str):
    """Charge le modele une fois. Le premier appel telecharge les poids."""
    global _model
    if _model is None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        _model = ChatterboxTurboTTS.from_pretrained(device)
    return _model


def _synthesize(request: dict) -> dict:
    import torchaudio

    model = _load(request.get("device", "cuda"))
    generate_kwargs = {
        "temperature": request.get("temperature", 0.8),
        "repetition_penalty": request.get("repetition_penalty", 1.2),
        # `exaggeration` pousse l'expressivite. Au-dela de 0.5 la diction
        # devient theatrale, ce qui s'entend comme un defaut sur une
        # narration explicative.
        "exaggeration": request.get("exaggeration", 0.0),
        "cfg_weight": request.get("cfg_weight", 0.0),
        # La normalisation interne est desactivee : le pipeline applique
        # deja `loudnorm` a -14 LUFS au montage, et deux normalisations
        # successives ecrasent la dynamique.
        "norm_loudness": False,
    }
    prompt = request.get("voice_sample")
    if prompt:
        generate_kwargs["audio_prompt_path"] = prompt

    wav = model.generate(request["text"], **generate_kwargs)
    torchaudio.save(request["out_path"], wav, model.sr)
    return {
        "ok": True,
        "sample_rate": model.sr,
        "duration": wav.shape[-1] / model.sr,
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = _synthesize(json.loads(line))
        except Exception as exc:
            response = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-800:],
            }
        _CHANNEL.write(json.dumps(response) + "\n")
        _CHANNEL.flush()


if __name__ == "__main__":
    main()
