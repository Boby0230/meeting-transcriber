"""
High-level orchestration of the transcription pipeline.

The pipeline runs one job at a time (guarded by a module-level lock) so
multiple uploads don't fight over the GPU. Optional steps that fail are
recorded as warnings — the transcript itself is always preserved.
"""

import logging
import threading
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


# Single GPU/CPU resource — at most one transcription job runs at a time.
# Subsequent jobs queue inside acquire_job_slot() and report "queued" to
# the polling client until they reach the head of the line.
_PIPELINE_LOCK = threading.Lock()


def acquire_job_slot():
    """Context manager: block until the pipeline slot is free."""
    return _PIPELINE_LOCK


def queue_is_busy() -> bool:
    """True if another job is currently holding the pipeline slot."""
    locked = _PIPELINE_LOCK.acquire(blocking=False)
    if locked:
        _PIPELINE_LOCK.release()
        return False
    return True


# ── Options & result types ────────────────────────────────────────────

@dataclass
class PipelineOptions:
    language: Optional[str] = None   # 'ro', 'en', or None for auto-detect
    diarize: bool = False
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None


@dataclass
class PipelineResult:
    transcript: str
    language: str
    word_count: int
    diarized: bool = False
    warnings: list[str] = field(default_factory=list)


# ── Main entry point ──────────────────────────────────────────────────

def run_pipeline(audio_path: str,
                 options: PipelineOptions,
                 on_progress: Optional[Callable] = None) -> PipelineResult:
    """
    Run transcribe → optional diarize against `audio_path`.

    Transcription failing raises (the caller marks the job as errored).
    Diarization failing is caught: the failure goes into result.warnings and
    the plain transcript is returned.
    """
    from transcriber import transcribe

    warnings: list[str] = []

    def warn(step: str, exc: Exception):
        traceback.print_exc()
        msg = f"{step} failed: {exc} — kept current transcript"
        warnings.append(msg)
        if on_progress:
            on_progress("warning", msg)
        log.warning(msg)

    # ── Transcribe (fatal if this fails) ─────────────────────────
    # Silence trimming is disabled when diarizing so whisper's timestamps
    # match the original audio (which pyannote also sees).
    transcribe_result = transcribe(
        audio_path,
        language=options.language,
        on_progress=on_progress,
        trim_silence=not options.diarize,
    )
    transcript: str = transcribe_result["text"]
    segments: list[dict] = transcribe_result["segments"]
    detected_lang: str = (
        transcribe_result.get("language") or options.language or "en"
    )

    diarized = False

    # ── Diarize (optional, non-fatal) ────────────────────────────
    if options.diarize:
        try:
            from diarizer import diarize, format_dialogue
            if on_progress:
                on_progress("diarizing", "Starting speaker diarization...", 78)
            turns = diarize(
                audio_path,
                on_progress=on_progress,
                min_speakers=options.min_speakers,
                max_speakers=options.max_speakers,
            )
            transcript = format_dialogue(segments, turns, include_timestamps=True)
            diarized = True
            if on_progress:
                on_progress("diarizing", "Speaker diarization done", 95)
        except Exception as e:
            warn("Diarization", e)

    if on_progress:
        on_progress("done", "Pipeline complete", 100)

    return PipelineResult(
        transcript=transcript,
        language=detected_lang,
        word_count=len(transcript.split()),
        diarized=diarized,
        warnings=warnings,
    )
