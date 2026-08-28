"""Configuration typee : secrets via .env, definition des chaines via YAML.

Deux sources volontairement separees :
  - `Settings`  : ce qui est secret et propre a la machine (cles d'API).
  - `channels.yaml` : ce qui est editorial et versionnable (niche, voix, style).
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mediaaut.core.paths import CONFIG, ROOT


class Settings(BaseSettings):
    """Secrets et chemins dependants de la machine, lus depuis `.env`."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str | None = None
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None

    youtube_client_secrets: str = "secrets/youtube_client_secret.json"
    ig_user_id: str | None = None
    ig_access_token: str | None = None
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None

    def require(self, field: str) -> str:
        """Recupere un secret en echouant tot et clairement s'il manque."""
        value = getattr(self, field, None)
        if not value:
            raise RuntimeError(
                f"{field.upper()} absent. Ajoute-le dans {ROOT / '.env'} "
                f"(modele disponible dans .env.example)."
            )
        return str(value)


class RenderConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    safe_top: float = 0.12
    safe_bottom: float = 0.20
    font: str = "Montserrat-ExtraBold"
    music_gain_db: float = -22.0
    voice_gain_db: float = 0.0
    templates: list[str] = Field(default_factory=lambda: ["bold_center"])


class VoiceConfig(BaseModel):
    provider: Literal["kokoro", "edge"] = "kokoro"
    voice_id: str = "am_michael"
    speed: float = 1.0


class SubtitleConfig(BaseModel):
    max_chars_per_cue: int = 22
    highlight: bool = True
    style: Literal["pop", "clean", "boxed"] = "pop"


class ScheduleConfig(BaseModel):
    shorts_per_day: int = 1
    times: list[str] = Field(default_factory=lambda: ["09:00"])


class ChannelConfig(BaseModel):
    id: str
    name: str
    language: str = "en"
    niche: str = ""
    angle: str = ""
    enabled: bool = True
    platforms: list[str] = Field(default_factory=list)
    render: RenderConfig = Field(default_factory=RenderConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fusion recursive : `override` gagne, les cles absentes heritent de `base`."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def load_channels(path: str | None = None) -> dict[str, ChannelConfig]:
    """Charge channels.yaml en appliquant le bloc `defaults` a chaque chaine."""
    config_path = CONFIG / "channels.yaml" if path is None else ROOT / path
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults", {})

    channels: dict[str, ChannelConfig] = {}
    for entry in raw.get("channels", []):
        merged = _merge(defaults, entry)
        channel = ChannelConfig(**merged)
        if channel.id in channels:
            raise ValueError(f"id de chaine duplique dans channels.yaml : {channel.id}")
        channels[channel.id] = channel
    return channels


def get_channel(channel_id: str) -> ChannelConfig:
    channels = load_channels()
    if channel_id not in channels:
        known = ", ".join(channels) or "(aucune)"
        raise KeyError(f"chaine inconnue : {channel_id}. Disponibles : {known}")
    return channels[channel_id]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
