"""Settings read from environment variables, with defaults that work offline.

Every value can be overridden without touching code:

    OLLAMA_HOST          where Ollama listens          (http://127.0.0.1:11434)
    THALI_MODEL          vision model tag              (gemma4:e4b)
    THALI_TIMEOUT        seconds for one model call    (180)
    THALI_HEALTH_TIMEOUT seconds for the status check  (3)
    THALI_MAX_RETRIES    harness retries after attempt 1 (2)
    THALI_DB             SQLite file path              (data/mythali.db)
    THALI_MAX_UPLOAD_MB  largest accepted photo        (15)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Fixed by the pipeline design rather than by deployment.
MAX_IMAGE_SIDE = 1600
JPEG_QUALITY = 88
THUMBNAIL_SIDE = 240
DESCRIPTION_MAX_CHARS = 600


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {raw!r}")
    return value


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {raw!r}")
    return value


def normalise_host(raw: str) -> str:
    """Turn Ollama-style host values into a base URL.

    Ollama itself accepts OLLAMA_HOST as "host:port" with no scheme, and as
    0.0.0.0 when it listens on every interface. Neither is a usable client
    address, so both are fixed here.
    """
    host = raw.strip().rstrip("/")
    if "://" not in host:
        host = f"http://{host}"
    scheme, _, rest = host.partition("://")
    if rest.startswith("0.0.0.0"):
        rest = "127.0.0.1" + rest[len("0.0.0.0"):]
    if ":" not in rest.split("/", 1)[0]:
        rest = f"{rest}:11434"
    return f"{scheme}://{rest}"


def _resolve_db_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    ollama_host: str
    model: str
    timeout: float
    health_timeout: float
    max_retries: int
    db_path: Path
    max_upload_bytes: int

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


def load_settings() -> Settings:
    return Settings(
        ollama_host=normalise_host(_env_str("OLLAMA_HOST", "http://127.0.0.1:11434")),
        model=_env_str("THALI_MODEL", "gemma4:cloud"),
        timeout=_env_float("THALI_TIMEOUT", 180.0, 1.0),
        health_timeout=_env_float("THALI_HEALTH_TIMEOUT", 3.0, 0.5),
        max_retries=_env_int("THALI_MAX_RETRIES", 2, 0),
        db_path=_resolve_db_path(_env_str("THALI_DB", "data/mythali.db")),
        max_upload_bytes=_env_int("THALI_MAX_UPLOAD_MB", 15, 1) * 1024 * 1024,
    )


settings = load_settings()
