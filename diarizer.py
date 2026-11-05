"""
Speaker diarization using pyannote.audio (3.x and 4.x compatible).

Lazy-loaded — pyannote is heavy and only needed when the user opts in.
First call downloads the diarization model from HuggingFace, which requires:

  1. `pip install pyannote.audio`
  2. An HF token in the HF_TOKEN environment variable.
  3. Acceptance of the model licenses at:
       https://huggingface.co/pyannote/speaker-diarization-3.1
       https://huggingface.co/pyannote/segmentation-3.0
       https://huggingface.co/pyannote/speaker-diarization-community-1   (pyannote 4.x only)

`is_available()` returns (ok, message) so the caller can give a useful
error at request time rather than after a long-running job.
"""

import logging
import os
import string
import subprocess
from typing import Callable, Optional

import config

log = logging.getLogger(__name__)


_pipeline = None


# ── Availability check ────────────────────────────────────────────────

def is_available() -> tuple[bool, str]:
    """Cheap precheck: can we actually run diarization?"""
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return False, (
            "pyannote.audio is not installed. "
            "Run: pip3 install pyannote.audio"
        )
    if not _hf_token():
        return False, (
            "HF_TOKEN env var is not set. Get a token at "
            "https://huggingface.co/settings/tokens and accept the model "
            "license at https://huggingface.co/pyannote/speaker-diarization-3.1"
        )
    return True, "ok"


def _hf_token() -> Optional[str]:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


# ── Pipeline loading ──────────────────────────────────────────────────

def _get_pipeline():
    """Lazy-load and cache the pyannote pipeline."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    from pyannote.audio import Pipeline
    import torch

    log.info("Loading diarization pipeline %s", config.DIARIZATION_MODEL)
    pipeline = Pipeline.from_pretrained(
        config.DIARIZATION_MODEL, token=_hf_token()
    )

    # Apple Silicon GPU when available; CUDA on Linux; CPU otherwise.
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))
        log.info("Diarization pipeline using MPS (Apple Silicon GPU)")
    elif torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        log.info("Diarization pipeline using CUDA")
    else:
        log.info("Diarization pipeline using CPU")

    _pipeline = pipeline
    return pipeline


# ── Annotation extraction (works for pyannote 3.x and 4.x) ────────────

def _extract_annotation(pipeline_output):
    """
    Pyannote 3.x: pipeline returns an Annotation directly.
    Pyannote 4.x: pipeline returns a DiarizeOutput with .exclusive_speaker_diarization
                  (Annotation with non-overlapping turns — what we want for
                  aligning with whisper segments).
    """
    if hasattr(pipeline_output, "exclusive_speaker_diarization"):
        return pipeline_output.exclusive_speaker_diarization
    if hasattr(pipeline_output, "speaker_diarization"):
        return pipeline_output.speaker_diarization
    return pipeline_output  # pyannote 3.x: already an Annotation


# ── Audio loading ─────────────────────────────────────────────────────

SAMPLE_RATE = 16000


def _load_waveform_16k(file_path: str):
    """Decode any audio file to a (1, samples) float32 torch tensor at 16 kHz."""
    import numpy as np
    import torch

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", file_path,
         "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32).copy()
    if samples.size == 0:
        raise RuntimeError("ffmpeg decoded no audio from the file")
    return torch.from_numpy(samples).unsqueeze(0)


# ── Main entry point ──────────────────────────────────────────────────

def diarize(file_path: str,
            on_progress: Optional[Callable] = None,
            min_speakers: Optional[int] = None,
            max_speakers: Optional[int] = None
            ) -> list[tuple[float, float, str]]:
    """
    Run speaker diarization on an audio file.

    Returns a list of (start_sec, end_sec, speaker_label) turns, sorted by
    start time. Speaker labels are remapped from pyannote's SPEAKER_00 etc.
    to human-friendly 'Speaker A', 'Speaker B', ... in order of first
    appearance.
    """
    def emit(stage, detail, percent=None):
        if on_progress:
            on_progress(stage, detail, percent)
        log.info("[%s] %s", stage, detail)

    emit("diarizing", "Loading diarization pipeline (first run downloads ~1GB)...")
    pipeline = _get_pipeline()

    # Decode to 16 kHz mono float32 with ffmpeg and hand pyannote the samples
    # in memory. Passing a file path makes pyannote 4.x read it through
    # torchcodec, which isn't usable in every install (the Linux image has no
    # working torchcodec). A waveform also has exact sample boundaries, which
    # avoids the "expected N samples got M" errors some m4a files caused.
    emit("diarizing", "Preparing audio for diarization (ffmpeg)...")
    waveform = _load_waveform_16k(file_path)

    emit("diarizing", "Running speaker diarization...")
    kwargs = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers

    output = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **kwargs)
    annotation = _extract_annotation(output)

    # Collect raw turns, then remap labels (SPEAKER_00 → Speaker A) by order
    # of first appearance so the output is consistent and readable.
    raw_turns = [
        (turn.start, turn.end, label)
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]
    raw_turns.sort(key=lambda t: t[0])

    label_map: dict[str, str] = {}
    turns: list[tuple[float, float, str]] = []
    for start, end, raw_label in raw_turns:
        if raw_label not in label_map:
            idx = len(label_map)
            label_map[raw_label] = (
                f"Speaker {string.ascii_uppercase[idx]}"
                if idx < 26
                else f"Speaker {idx + 1}"
            )
        turns.append((start, end, label_map[raw_label]))

    emit("diarizing",
         f"Found {len(label_map)} speakers across {len(turns)} turns")
    return turns


# ── Merging diarization with whisper segments ─────────────────────────

def _speaker_at(turns: list[tuple[float, float, str]], t: float) -> Optional[str]:
    """Speaker whose turn contains time `t`, or closest within 0.5s."""
    closest: Optional[str] = None
    closest_dist = float("inf")
    for start, end, speaker in turns:
        if start <= t <= end:
            return speaker
        dist = start - t if t < start else t - end
        if dist < closest_dist:
            closest_dist = dist
            closest = speaker
    return closest if closest_dist <= 0.5 else None


def _dominant_speaker(turns: list[tuple[float, float, str]],
                      seg_start: float, seg_end: float) -> Optional[str]:
    """Speaker whose turn overlaps the most with [seg_start, seg_end]."""
    overlaps: dict[str, float] = {}
    for start, end, speaker in turns:
        if end < seg_start or start > seg_end:
            continue
        overlap = min(end, seg_end) - max(start, seg_start)
        if overlap > 0:
            overlaps[speaker] = overlaps.get(speaker, 0) + overlap
    if overlaps:
        return max(overlaps.items(), key=lambda kv: kv[1])[0]
    return _speaker_at(turns, (seg_start + seg_end) / 2)


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def format_dialogue(segments: list[dict],
                    turns: list[tuple[float, float, str]],
                    include_timestamps: bool = True) -> str:
    """
    Merge whisper segments with diarization turns into a dialogue transcript.
    Consecutive segments by the same speaker are merged into one paragraph.

    Each paragraph: `[hh:mm:ss] Speaker X: text...`
    """
    if not segments:
        return ""

    annotated = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start))
        speaker = _dominant_speaker(turns, start, end) or "Speaker ?"
        annotated.append((start, end, speaker, text))

    if not annotated:
        return ""

    lines = []
    cur_speaker = None
    cur_start = 0.0
    cur_text_parts: list[str] = []

    def flush():
        if not cur_text_parts:
            return
        body = " ".join(cur_text_parts).strip()
        prefix = f"[{_fmt_ts(cur_start)}] " if include_timestamps else ""
        lines.append(f"{prefix}{cur_speaker}: {body}")

    for start, _end, speaker, text in annotated:
        if speaker != cur_speaker:
            flush()
            cur_speaker = speaker
            cur_start = start
            cur_text_parts = [text]
        else:
            cur_text_parts.append(text)
    flush()

    return "\n\n".join(lines)
