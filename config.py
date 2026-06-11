"""
Centralized configuration for the Meeting Transcriber.

All knobs read from environment variables with sensible defaults so the app
can be tuned per-deployment without code changes.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """
    Minimal, dependency-free .env loader. Reads KEY=VALUE lines from a `.env`
    file next to this module and sets them in the environment if not already
    set. Lets `HF_TOKEN` etc. "just work" regardless of how the app is
    launched (python app.py, gunicorn, run.sh). `.env` is gitignored.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


# ── Server ────────────────────────────────────────────────────────────
HOST = os.environ.get("MS_HOST", "127.0.0.1")
PORT = _env_int("MS_PORT", 5001)
MAX_UPLOAD_MB = _env_int("MS_MAX_UPLOAD_MB", 500)

# ── Storage ───────────────────────────────────────────────────────────
DATA_DIR = _env_path("MS_DATA_DIR", BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "jobs.db")
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Transcription ─────────────────────────────────────────────────────
WHISPER_MODEL = os.environ.get(
    "MS_WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx"
)
CHUNK_MINUTES = _env_int("MS_CHUNK_MINUTES", 10)
CHUNK_THRESHOLD_MIN = _env_int("MS_CHUNK_THRESHOLD_MIN", 15)

# ── Diarization ───────────────────────────────────────────────────────
DIARIZATION_MODEL = os.environ.get(
    "MS_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)

# ── Logging ───────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("MS_LOG_LEVEL", "INFO")
