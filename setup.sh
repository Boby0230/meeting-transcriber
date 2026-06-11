#!/usr/bin/env bash
#
# One-time setup for Meeting Transcriber on an Apple Silicon Mac.
# Safe to re-run. Creates a local .venv and installs dependencies.
#
#   ./setup.sh
#
set -euo pipefail
cd "$(dirname "$0")"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
die()  { printf "  \033[31m✗ %s\033[0m\n" "$1"; exit 1; }

bold "🎙  Meeting Transcriber — setup"
echo

# ── 1. Platform checks ────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || die "This app needs macOS (it uses mlx-whisper, which is Apple-only)."
if [ "$(uname -m)" != "arm64" ]; then
  die "This app needs an Apple Silicon Mac (M1/M2/M3/M4). mlx-whisper won't run on Intel."
fi
ok "Apple Silicon macOS detected"

# ── 2. Homebrew + ffmpeg ──────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew not found. Install it from https://brew.sh then re-run ./setup.sh"
fi
ok "Homebrew present"

if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg not found — installing via Homebrew..."
  brew install ffmpeg
fi
ok "ffmpeg present"

# ── 3. Python ─────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.9+ (brew install python)."
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || die "Python 3.9+ required (found $PYV)."
ok "Python $PYV"

# ── 4. Virtualenv + core deps ─────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "  Creating virtual environment (.venv)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
ok "Virtual environment ready"

echo "  Installing core dependencies (this can take a few minutes)..."
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r requirements.txt
ok "Core dependencies installed"

# ── 5. Optional: speaker diarization ──────────────────────────────────
echo
bold "Speaker diarization (optional)"
echo "  Adds 'who said what' labels. Needs a FREE HuggingFace token and"
echo "  pulls in PyTorch (~2 GB). You can skip this and add it later."
echo
printf "  Install speaker diarization now? [y/N] "
read -r ANSWER || ANSWER=""
if [[ "$ANSWER" =~ ^[Yy]$ ]]; then
  echo "  Installing pyannote.audio (large download)..."
  python3 -m pip install --quiet "pyannote.audio>=4.0"
  ok "pyannote.audio installed"

  # Seed .env with an HF token
  [ -f .env ] || cp .env.example .env
  if grep -qE '^HF_TOKEN=.+' .env 2>/dev/null; then
    ok "HF_TOKEN already set in .env"
  else
    echo
    echo "  Get a free token at: https://huggingface.co/settings/tokens"
    printf "  Paste your HuggingFace token (or press Enter to do it later): "
    read -r HF || HF=""
    if [ -n "$HF" ]; then
      # Replace or append HF_TOKEN line
      if grep -q '^HF_TOKEN=' .env; then
        /usr/bin/sed -i '' "s|^HF_TOKEN=.*|HF_TOKEN=$HF|" .env
      else
        printf "HF_TOKEN=%s\n" "$HF" >> .env
      fi
      ok "Saved HF_TOKEN to .env"
    else
      warn "No token saved — edit .env later to enable diarization."
    fi
  fi
  echo
  warn "One-time: accept the model licenses (logged into HuggingFace) at:"
  echo "    https://huggingface.co/pyannote/speaker-diarization-3.1"
  echo "    https://huggingface.co/pyannote/segmentation-3.0"
  echo "    https://huggingface.co/pyannote/speaker-diarization-community-1"
else
  warn "Skipped speaker diarization. Transcription still works fully."
fi

echo
bold "✅ Setup complete"
echo "  Start the app with:  ./run.sh"
echo "  Then open:           http://localhost:5001"
