# Meeting Transcriber

Local web app that takes audio recordings of meetings (M4A, MP3, MP4, etc.)
and produces a clean transcript with optional speaker labels. Everything
runs **locally on Apple Silicon** — no cloud, no API keys, no per-use cost.

The output is a **transcript**, not a summary. Take it to the LLM of your
choice (ChatGPT, Claude, whatever) with your own prompt for summarizing,
extracting action items, or any other analysis. That keeps this app simple
and lets you iterate on prompts without ever re-transcribing.

## What it does

```
audio file
   │
   ▼
mlx-whisper transcription      ← local, free, Apple Silicon GPU
   │
   ▼  (optional)
pyannote speaker diarization   ← local, free, needs a free HF token
   │
   ▼
clean transcript               ← exported as md / txt / json
```

## Requirements

- **Apple Silicon Mac** (M1/M2/M3/M4). The transcription engine (mlx-whisper)
  does not run on Intel Macs, Windows, or Linux.
- [Homebrew](https://brew.sh) and Python 3.9+ (the setup script checks both).

## Quick start

```bash
git clone https://github.com/Boby0230/meeting-transcriber.git
cd meeting-transcriber
./setup.sh      # one-time: installs deps, optionally sets up diarization
./run.sh        # starts the app and opens your browser
```

That's it. `setup.sh` is interactive and safe to re-run; `run.sh` keeps your
Mac awake during long jobs and opens http://localhost:5001 once it's ready.

Prefer not to touch a terminal at all? Run `./launcher/build.sh` once to get a
double-clickable **Meeting Transcriber.app** — see
[Double-click launcher](#double-click-launcher-no-terminal).

**No `ANTHROPIC_API_KEY` or any paid secret is required** — everything runs
locally. The only optional credential is a free HuggingFace token, and only
if you want speaker labels (the setup script walks you through it).

### Manual run (if you'd rather not use the scripts)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
# optional diarization:
pip install pyannote.audio
cp .env.example .env   # then put your HF_TOKEN in .env
caffeinate -i python3 app.py
```

## Running & stopping the app

**Start** (opens your browser automatically once it's ready):

```bash
cd meeting-transcriber
./run.sh
```

The terminal stays busy showing live logs — that's expected. Keep the window
open while you use the app.

**Stop:** press **`Ctrl + C`** in that terminal. Closing the terminal window
also stops it.

**Keep it running after you close the terminal** (optional):

```bash
nohup ./run.sh > ~/meeting-transcriber.log 2>&1 &
```

Then stop it later with this — works no matter how it was started:

```bash
lsof -ti:5001 | xargs kill
```

**Good to know**

- Check if it's running: `lsof -i:5001`, or just open http://localhost:5001.
- `Address already in use` when starting means it's *already* running — just
  open the browser; don't start a second copy. Only one instance runs at a
  time (single GPU, single port).

## Double-click launcher (no Terminal)

`launcher/` builds a small macOS app so you can start everything from Finder
instead of a terminal:

```bash
./launcher/build.sh
```

That produces **`Meeting Transcriber.app`** in the project folder. Double-click
it and it will:

1. Start the server in the background if it isn't already running
2. Wait until the server is actually ready
3. Open http://localhost:5001 in your browser

Clicking it again while the server is already running just reopens the browser
— it won't start a second copy. Server output goes to `data/server.log`.

Drag the app to your Dock if you want it one click away. To stop the server,
see "Running & stopping the app" above (`lsof -ti:5001 | xargs kill`).

The `.app` is a build artifact and is gitignored — run `./launcher/build.sh`
once after cloning. It needs Pillow for the custom icon
(`.venv/bin/pip install Pillow`); without it the app still works and just
keeps the generic script icon.

## Production / sharing on your network

```bash
# Bind to all interfaces, one worker (the pipeline serializes jobs internally).
gunicorn -w 1 -b 0.0.0.0:5001 --timeout 0 wsgi:app
```

`--timeout 0` is important — gunicorn's default 30s worker timeout will kill
long transcription jobs.

To share with a colleague on the same network, use `-b 0.0.0.0:5001` (above)
and have them visit `http://<your-mac-ip>:5001`. Find your IP with
`ipconfig getifaddr en0`.

## Environment variables

| Var                       | Default                                  | Purpose                                  |
| ------------------------- | ---------------------------------------- | ---------------------------------------- |
| `HF_TOKEN`                | (only for diarization)                   | Free HuggingFace token for pyannote      |
| `MS_HOST`                 | `127.0.0.1`                              | Bind address                             |
| `MS_PORT`                 | `5001`                                   | Bind port                                |
| `MS_MAX_UPLOAD_MB`        | `500`                                    | Max upload size                          |
| `MS_DATA_DIR`             | `./data`                                 | Where the SQLite DB + uploads live       |
| `MS_WHISPER_MODEL`        | `mlx-community/whisper-large-v3-mlx`     | mlx-whisper HF repo                      |
| `MS_CHUNK_MINUTES`        | `10`                                     | Long-audio chunk size                    |
| `MS_CHUNK_THRESHOLD_MIN`  | `15`                                     | Files longer than this get chunked       |
| `MS_DIARIZATION_MODEL`    | `pyannote/speaker-diarization-3.1`       | pyannote pipeline                        |
| `MS_LOG_LEVEL`            | `INFO`                                   | Python logging level                     |

## Architecture

| File             | Purpose                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `app.py`         | Flask routes only                                                |
| `pipeline.py`    | Orchestrates transcribe → optional diarize, with the job lock    |
| `transcriber.py` | mlx-whisper wrapper, hallucination filter, ffmpeg chunking       |
| `diarizer.py`    | pyannote wrapper, speaker→dialogue formatting (3.x + 4.x)        |
| `storage.py`     | SQLite-backed `JobStore` (jobs survive restarts)                 |
| `config.py`      | Env-driven configuration                                         |
| `wsgi.py`        | gunicorn entrypoint                                              |

The pipeline runs one job at a time, gated by a module-level lock in
`pipeline.py`. Concurrent uploads queue and report their position to the
client, so two whisper jobs never fight for the GPU.

## Transcript quality

The transcriber is tuned to avoid Whisper's common failure modes:

- **Silence trimming** (ffmpeg) before transcription, so it isn't fed dead air.
- **`condition_on_previous_text=False`** so a single hallucination can't
  cascade through the rest of the transcript.
- **Tightened no-speech / logprob / compression thresholds** to drop
  low-confidence segments instead of inventing words.
- **A hallucination phrase filter** that strips the "thanks for watching" /
  "subscribe" / Korean-leak artifacts Whisper emits on silence, in several
  languages.

It uses `whisper-large-v3` (not the faster `turbo`) deliberately — quality
over speed.

## Linux and Docker

On anything other than an Apple Silicon Mac, the app uses
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU
instead of mlx-whisper. Same model (Whisper large-v3), same decoding
settings. `requirements.txt` installs the right engine for the machine.

```bash
docker build -t meeting-transcriber .
docker run --env-file .env -v mt_data:/data -v mt_models:/models \
  -p 127.0.0.1:5001:5001 meeting-transcriber
```

The first start downloads the model (~3 GB) into `/models`. On a CPU,
expect transcription to be several times slower than on an M-series Mac.
In the image the "Stop app" button is off (`ALLOW_SHUTDOWN=0`).

| Var | Default | Purpose |
| --- | --- | --- |
| `MS_ENGINE` | `auto` | `mlx`, `faster-whisper`, or `auto` (mlx on Apple Silicon) |
| `MS_FW_COMPUTE_TYPE` | `int8` | faster-whisper precision on CPU |
| `MS_FW_THREADS` | half the logical CPUs | faster-whisper CPU threads |
| `ALLOW_SHUTDOWN` | `1` | `0` hides the Stop app button and turns off its route |

## Known limits

- **CPU is slower.** Off Apple Silicon, faster-whisper runs on the CPU. A
  CUDA GPU would be much faster (not set up here yet).
- **No auth.** Anyone with network access to the host can upload and read
  transcripts. Fine for a trusted LAN, not for the open internet — put auth
  in front of it (e.g. basic auth in nginx) before exposing it.
- **One job at a time** by design — the GPU is the bottleneck.
- **No automatic cleanup** of old uploads in `data/uploads/`. Prune by hand
  or with a cron job if disk space matters.
