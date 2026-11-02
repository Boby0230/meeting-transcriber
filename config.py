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
# "mlx" (Apple Silicon GPU) or "faster-whisper" (CPU, any OS). "auto" picks
# mlx on an Apple Silicon Mac and faster-whisper everywhere else.
def _default_engine() -> str:
    import platform
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mlx"
    return "faster-whisper"


ENGINE = os.environ.get("MS_ENGINE", "auto").strip().lower()
if ENGINE == "auto":
    ENGINE = _default_engine()
if ENGINE not in ("mlx", "faster-whisper"):
    raise ValueError(f"MS_ENGINE must be auto, mlx or faster-whisper, not {ENGINE!r}")

# Same model (Whisper large-v3) in each engine's own format.
WHISPER_MODEL = os.environ.get(
    "MS_WHISPER_MODEL",
    "mlx-community/whisper-large-v3-mlx" if ENGINE == "mlx" else "large-v3",
)
# faster-whisper only: int8 is the fastest on CPU with near-identical quality.
FW_COMPUTE_TYPE = os.environ.get("MS_FW_COMPUTE_TYPE", "int8")
# faster-whisper only: CPU threads. Default: physical cores (half the logical ones).
FW_THREADS = _env_int("MS_FW_THREADS", max(1, (os.cpu_count() or 2) // 2))
CHUNK_MINUTES = _env_int("MS_CHUNK_MINUTES", 10)
CHUNK_THRESHOLD_MIN = _env_int("MS_CHUNK_THRESHOLD_MIN", 15)

# ── Diarization ───────────────────────────────────────────────────────
DIARIZATION_MODEL = os.environ.get(
    "MS_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)

# ── Server mode ───────────────────────────────────────────────────────
# The "Stop app" button. On by default for the Mac launcher; ALLOW_SHUTDOWN=0
# on the server, where Docker manages the process.
ALLOW_SHUTDOWN = os.environ.get("ALLOW_SHUTDOWN", "1") != "0"

# ── Logging ───────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("MS_LOG_LEVEL", "INFO")
