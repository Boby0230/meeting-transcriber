#!/usr/bin/env python3
"""
Meeting Transcriber — Flask web app.

Pipeline: upload audio → whisper transcribe (mlx or faster-whisper) → optional pyannote
speaker diarization → optional Claude cleanup pass → clean transcript.

Routes:
    GET  /                              UI
    POST /api/process                   start a new job, returns {job_id}
    GET  /api/status/<job_id>           poll for progress
    GET  /api/results/<job_id>          fetch transcript when ready
    GET  /api/jobs                      list recent jobs
    GET  /api/export/<job_id>/<fmt>     download transcript (md|txt|json)
"""

import json
import logging
import os
import signal
import sys
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# ── Dependency check ──────────────────────────────────────────────────
import config  # noqa: E402

_engine_pkg = ("mlx_whisper", "mlx-whisper") if config.ENGINE == "mlx" else ("faster_whisper", "faster-whisper")
_missing = []
for _pkg, _pip in [("flask", "flask"), _engine_pkg]:
    try:
        __import__(_pkg)
    except ImportError:
        _missing.append(_pip)
if _missing:
    print(f"❌ Missing: {', '.join(_missing)}\n   pip3 install {' '.join(_missing)}")
    sys.exit(1)

from flask import Flask, jsonify, render_template, request, Response, send_from_directory  # noqa: E402

import pipeline  # noqa: E402
from storage import JobStore  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

# ── App + store ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

store = JobStore(config.DB_PATH)

# A job interrupted by a restart would otherwise sit at 'running' forever.
# Safe here: at import time this process has no jobs in flight. Run with a
# single worker (see wsgi.py) so this happens exactly once per start.
_interrupted = store.reconcile_interrupted()
if _interrupted:
    log.warning("Marked %d interrupted job(s) as errored after restart", _interrupted)


# ── Background worker ─────────────────────────────────────────────────

def run_job(job_id: str, file_path: str, options: pipeline.PipelineOptions):
    """
    Wait for the pipeline slot, run the pipeline, persist results.
    Runs in a daemon thread spawned from /api/process.
    """
    def on_progress(stage: str, detail: str, percent=None):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "stage": stage,
            "message": detail,
        }
        store.append_log(job_id, entry)
        update = {"stage": stage}
        if percent is not None:
            update["percent"] = percent
        store.update(job_id, **update)

    try:
        # Mark queued; show position in queue if anything else is ahead
        if pipeline.queue_is_busy():
            store.update(job_id, status="queued", stage="queued", percent=0)
            store.append_log(job_id, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": "queued",
                "message": "Waiting for another job to finish...",
            })

        with pipeline.acquire_job_slot():
            store.update(job_id, status="running", stage="info", percent=1)

            result = pipeline.run_pipeline(
                file_path, options, on_progress=on_progress,
            )

            for warning in result.warnings:
                store.append_warning(job_id, warning)

            store.update(
                job_id,
                status="done",
                stage="done",
                percent=100,
                transcript=result.transcript,
                word_count=result.word_count,
                language=result.language,
                diarized=result.diarized,
            )
            store.append_log(job_id, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": "done",
                "message": "All done!" + (
                    f" (with {len(result.warnings)} warning(s))"
                    if result.warnings else ""
                ),
            })

    except Exception as exc:
        log.exception("Job %s failed", job_id)
        store.update(job_id, status="error", stage="error", error=str(exc))
        store.append_log(job_id, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "stage": "error",
            "message": str(exc),
        })

    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass


# ── Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", allow_shutdown=config.ALLOW_SHUTDOWN)


# ── Home screen ───────────────────────────────────────────────────────
# iOS fetches these without the login cookie, so they sit at the addresses Caddy lets
# through without a login (the @pwa list in the homelab repo). They hold no personal data.

@app.route("/apple-icon")
def apple_icon():
    return send_from_directory(app.static_folder, "apple-icon.png", mimetype="image/png", max_age=86400)


@app.route("/icon.svg")
def icon_svg():
    return send_from_directory(app.static_folder, "icon.svg", mimetype="image/svg+xml", max_age=86400)


@app.route("/manifest.webmanifest")
def manifest():
    body = {
        "name": "Meeting Transcriber",
        "short_name": "Transcriber",
        "description": "Meeting recordings to transcripts, with speaker labels.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0c0d0f",
        "theme_color": "#0c0d0f",
        "icons": [
            {"src": "/apple-icon", "sizes": "180x180", "type": "image/png", "purpose": "any"},
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    }
    return app.response_class(json.dumps(body), mimetype="application/manifest+json")


@app.route("/healthz")
def healthz():
    """Health check for Docker and the uptime monitor. Reveals no data."""
    return jsonify({"ok": True})


@app.route("/api/process", methods=["POST"])
def api_process():
    """Start a new job. Returns {job_id} immediately; client polls /api/status."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    upload = request.files["file"]
    if not upload.filename:
        return jsonify({"error": "Empty filename"}), 400

    options = pipeline.PipelineOptions(
        language=(request.form.get("language") or "auto"),
        diarize=request.form.get("diarize") == "true",
    )
    if options.language == "auto":
        options.language = None

    # Fail fast on diarization prereqs so the user doesn't wait through a
    # long transcription before hitting an HF_TOKEN error.
    if options.diarize:
        from diarizer import is_available
        ok, msg = is_available()
        if not ok:
            return jsonify({"error": f"Speaker diarization unavailable: {msg}"}), 400

    # Persist the upload under a stable path so the background worker
    # doesn't depend on a NamedTemporaryFile handle staying open.
    job_id = uuid.uuid4().hex[:8]
    suffix = Path(upload.filename).suffix or ".m4a"
    saved_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    upload.save(str(saved_path))

    size_mb = saved_path.stat().st_size / (1024 * 1024)
    log.info("New job %s: %s (%.1f MB) [diarize=%s]",
             job_id, upload.filename, size_mb, options.diarize)

    store.create(job_id, upload.filename, {
        "language": options.language,
        "diarize": options.diarize,
    })
    store.append_log(job_id, {
        "time": datetime.now().strftime("%H:%M:%S"),
        "stage": "upload",
        "message": f"File received: {upload.filename} ({size_mb:.1f} MB)",
    })

    # Set duration up front so the UI shows it during the queue wait
    try:
        from transcriber import get_audio_duration
        duration_min = round(get_audio_duration(str(saved_path)) / 60, 1)
        store.update(job_id, duration_min=duration_min)
    except Exception:
        pass

    threading.Thread(
        target=run_job, args=(job_id, str(saved_path), options),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    d = job.to_dict()
    # Don't ship the (potentially huge) transcript in poll responses.
    d.pop("transcript", None)
    d["has_transcript"] = bool(job.transcript)
    return jsonify(d)


@app.route("/api/results/<job_id>")
def api_results(job_id):
    job = store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Allow fetching whatever transcript exists, even on partial failures.
    # Failed jobs answer too, so opening one from the list can say why it failed.
    if not job.transcript and job.status not in ("done", "error"):
        return jsonify({"error": "Job not finished yet"}), 400
    return jsonify({
        "transcript": job.transcript or "",
        "word_count": job.word_count,
        "filename": job.filename,
        "duration_min": job.duration_min,
        "language": job.language,
        "diarized": job.diarized,
        "cleaned": job.cleaned,
        "warnings": job.warnings,
        "status": job.status,
        "error": job.error,
    })


@app.route("/api/jobs")
def api_jobs():
    """Recent jobs, newest first."""
    jobs = store.list_recent(limit=50)
    return jsonify({
        "jobs": [
            {
                "id": j.id,
                "filename": j.filename,
                "status": j.status,
                "created_at": j.created_at,
                "duration_min": j.duration_min,
                "word_count": j.word_count,
                "diarized": j.diarized,
                "cleaned": j.cleaned,
            }
            for j in jobs
        ],
    })


def _content_disposition(filename: str) -> str:
    """
    Build an RFC 6266 Content-Disposition value for an attachment.

    HTTP headers may only contain latin-1 characters, so a filename with
    diacritics (e.g. "Strada Arcașilor.txt") raises UnicodeEncodeError if
    embedded directly. We emit both forms:
      - `filename="..."`      — quoted ASCII fallback (accents stripped),
                                also protecting spaces/commas from being
                                misparsed as header syntax.
      - `filename*=UTF-8''…`  — percent-encoded original, which every
                                current browser prefers.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    # Strip characters that would break out of the quoted string.
    ascii_name = ascii_name.replace('"', "").replace("\\", "").strip()
    # A name that was entirely non-ASCII (e.g. "会議.json") leaves just the
    # extension — give the fallback a usable stem.
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = f"transcript{ascii_name}"
    utf8_name = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


@app.route("/api/export/<job_id>/<fmt>")
def api_export(job_id, fmt):
    job = store.get(job_id)
    if not job or not job.transcript:
        return jsonify({"error": "Job not ready or has no transcript"}), 400

    base = Path(job.filename).stem if job.filename else "transcript"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    download_name = f"{base}_{stamp}"

    if fmt == "md":
        body = "# Transcript\n\n"
        if job.warnings:
            body += "> ⚠️ " + "\n> ".join(job.warnings) + "\n\n"
        body += job.transcript
        return Response(
            body, mimetype="text/markdown",
            headers={"Content-Disposition": _content_disposition(f"{download_name}.md")},
        )

    if fmt == "txt":
        body = job.transcript
        return Response(
            body, mimetype="text/plain",
            headers={"Content-Disposition": _content_disposition(f"{download_name}.txt")},
        )

    if fmt == "json":
        data = {
            "filename": job.filename,
            "duration_minutes": job.duration_min,
            "word_count": job.word_count,
            "language": job.language,
            "diarized": job.diarized,
            "cleaned": job.cleaned,
            "warnings": job.warnings,
            "transcript": job.transcript,
            "created_at": job.created_at,
        }
        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": _content_disposition(f"{download_name}.json")},
        )

    return jsonify({"error": f"Unknown format: {fmt}"}), 400


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """
    Stop the server (used by the "Stop app" button). Replies first, then
    exits, so the browser gets a response before the process goes away.

    Refuses while a transcription is in flight unless force=true: the
    transcript is only persisted once the pipeline finishes, so killing the
    server mid-job throws that work away.
    """
    if not config.ALLOW_SHUTDOWN:
        return jsonify({"error": "Not found"}), 404

    force = request.args.get("force") == "true"
    if pipeline.queue_is_busy() and not force:
        log.info("Shutdown refused — a job is still running")
        return jsonify({
            "stopping": False,
            "busy": True,
            "error": "A transcription is still running.",
        }), 409

    log.info("Shutdown requested from the UI (force=%s)", force)
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    return jsonify({"stopping": True, "busy": False})


# ── Dev server ────────────────────────────────────────────────────────

def _warmup():
    """Pre-load whisper model so the first job doesn't pay the cost."""
    from transcriber import preload_model
    preload_model()


def _print_banner():
    print()
    print("  🎙  Meeting Transcriber")
    print("  ══════════════════════")
    print(f"  Transcription:    FREE   ({config.ENGINE}, {config.WHISPER_MODEL})")
    print(f"  Diarization:      FREE   (pyannote, optional)")
    print(f"  Fully local — no API keys required.")
    print()
    print(f"  Data dir:     {config.DATA_DIR}")
    print(f"  Open →        http://{config.HOST}:{config.PORT}")
    print()
    if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")):
        print("  ℹ️  HF_TOKEN not set — speaker diarization will be unavailable")
    print()


if __name__ == "__main__":
    _print_banner()
    _warmup()
    app.run(host=config.HOST, port=config.PORT, debug=False)
