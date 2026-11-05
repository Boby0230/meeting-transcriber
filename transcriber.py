"""
Local transcription engine: mlx-whisper on Apple Silicon, faster-whisper
elsewhere (Linux server, CPU). config.ENGINE picks one.

Pipeline:
  1. ffmpeg → mono 16 kHz mp3, optionally with silences trimmed
  2. If audio is long, split into N-minute chunks for progress + memory
  3. Whisper on each chunk with hardened decoding settings to suppress
     the YouTube-style hallucinations ("Thanks for watching!" etc.) that
     whisper emits on silence or low-confidence audio
  4. Post-process to drop known hallucination phrases + immediate repeats
"""

import glob
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Callable, Optional

import config

log = logging.getLogger(__name__)


# ── Hallucination filter ──────────────────────────────────────────────
# Phrases whisper frequently invents on silence / music / low-volume audio.
# Matched case-insensitively against punctuation-stripped segment text.

HALLUCINATION_PHRASES = [
    # English (YouTube boilerplate)
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subscribe to my channel",
    "subscribe to our channel",
    "like and subscribe",
    "don't forget to subscribe",
    "see you in the next video",
    "see you next time",
    "see you next video",
    "transcribed by",
    "subtitles by the amara.org community",
    "subtitled by",
    "subtitles by",
    "music",
    # Romanian
    "mulțumim pentru vizionare",
    "mulțumesc pentru vizionare",
    "să vă mulțumim pentru vizionare",
    "vă mulțumim pentru vizionare",
    "abonați-vă",
    "subtitrare",
    # Korean (very common whisper leak)
    "시청해주셔서 감사합니다",
    "감사합니다",
    "구독과 좋아요",
    # Spanish / Portuguese / French / German
    "gracias por ver",
    "obrigado por assistir",
    "merci d'avoir regardé",
    "vielen dank fürs zuschauen",
]

_HALLUC_LOOKUP = {
    re.sub(r"[^\w\s]", "", p).strip().lower() for p in HALLUCINATION_PHRASES
}


# ── ffmpeg helpers ────────────────────────────────────────────────────

def get_audio_duration(file_path: str) -> float:
    """Audio duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", file_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _silence_filter() -> str:
    """
    Trim head/tail silence and collapse internal silences longer than 2s
    down to 0.5s. -45 dB threshold leaves quiet speech intact.
    """
    head_tail = (
        "silenceremove=start_periods=1:start_silence=0.3:start_threshold=-45dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.3:start_threshold=-45dB,"
        "areverse"
    )
    internal = (
        "silenceremove=stop_periods=-1:stop_duration=2:stop_threshold=-45dB"
    )
    return f"{head_tail},{internal}"


def split_audio(file_path: str,
                chunk_minutes: int = 10,
                trim_silence: bool = True) -> list[str]:
    """
    Split into ~chunk_minutes-long mono 16 kHz mp3 chunks. Set
    trim_silence=False when timestamps must align with the original timeline
    (e.g. for diarization alignment).
    """
    chunk_dir = tempfile.mkdtemp(prefix="meeting_chunks_")
    chunk_pattern = os.path.join(chunk_dir, "chunk_%03d.mp3")

    cmd = ["ffmpeg", "-y", "-i", file_path]
    if trim_silence:
        cmd += ["-af", _silence_filter()]
    cmd += ["-f", "segment", "-segment_time", str(chunk_minutes * 60),
            "-ac", "1", "-ar", "16000", "-b:a", "48k", chunk_pattern]
    subprocess.run(cmd, capture_output=True, check=True)

    return sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.mp3")))


def preprocess_short(file_path: str, trim_silence: bool = True) -> str:
    """Resample (and optionally silence-trim) a short file into a temp mp3."""
    out_dir = tempfile.mkdtemp(prefix="meeting_pre_")
    out_path = os.path.join(out_dir, "audio.mp3")
    cmd = ["ffmpeg", "-y", "-i", file_path]
    if trim_silence:
        cmd += ["-af", _silence_filter()]
    cmd += ["-ac", "1", "-ar", "16000", "-b:a", "48k", out_path]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


# ── Whisper ───────────────────────────────────────────────────────────
#
# Decoding settings tuned to reduce hallucinations, shared by both engines:
#
# - condition_on_previous_text=False: stops a single hallucination from
#   cascading into the rest of the transcript.
# - compression_ratio_threshold=2.0: reject overly repetitive segments;
#   whisper retries them with a higher temperature.
# - no_speech_threshold=0.6 + logprob_threshold=-0.8: drop low-confidence
#   silent segments instead of inventing words.
#
# Word-level timestamps are intentionally NOT requested. Speaker diarization
# aligns on segment-level start/end times, so word timestamps would roughly
# double decode time for data we never use.

DECODING = {
    "condition_on_previous_text": False,
    "compression_ratio_threshold": 2.0,
    "no_speech_threshold": 0.6,
    "logprob_threshold": -0.8,
    "temperature": (0.0, 0.2, 0.4, 0.6),
}

_fw_model = None


def _faster_whisper_model():
    """Load the faster-whisper model once and keep it."""
    global _fw_model
    if _fw_model is None:
        from faster_whisper import WhisperModel
        log.info("Loading faster-whisper model %s (%s, %s threads) ...",
                 config.WHISPER_MODEL, config.FW_COMPUTE_TYPE, config.FW_THREADS)
        _fw_model = WhisperModel(
            config.WHISPER_MODEL,
            device="cpu",
            compute_type=config.FW_COMPUTE_TYPE,
            cpu_threads=config.FW_THREADS,
        )
    return _fw_model


def _load_audio_16k(path: str):
    """
    Decode any audio file to 16 kHz mono float32 samples with ffmpeg.
    faster-whisper accepts samples directly, which skips its own decoder
    (PyAV); newer PyAV releases dropped an option faster-whisper still passes.
    """
    import numpy as np
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def _run_whisper(audio, language: Optional[str]) -> dict:
    """
    Transcribe one file path (or a float32 numpy array) with the configured
    engine. Returns {"segments": [{start, end, text}, ...], "language": str}.
    """
    if config.ENGINE == "mlx":
        import mlx_whisper
        kwargs = {"path_or_hf_repo": config.WHISPER_MODEL, "verbose": False, **DECODING}
        if language:
            kwargs["language"] = language
        result = mlx_whisper.transcribe(audio, **kwargs)
        return {"segments": result.get("segments", []), "language": result.get("language")}

    model = _faster_whisper_model()
    if isinstance(audio, str):
        audio = _load_audio_16k(audio)
    fw = dict(DECODING)
    fw["log_prob_threshold"] = fw.pop("logprob_threshold")
    fw["temperature"] = list(fw["temperature"])
    segments, info = model.transcribe(audio, language=language or None, **fw)
    out = [{"start": seg.start, "end": seg.end, "text": seg.text} for seg in segments]
    return {"segments": out, "language": info.language}


def preload_model():
    """Download + warm the model so the first real transcription is fast."""
    import numpy as np
    log.info("Loading Whisper model %s (%s) ...", config.WHISPER_MODEL, config.ENGINE)
    _run_whisper(np.zeros(16000, dtype=np.float32), None)
    log.info("Whisper model ready")


# ── Post-processing ───────────────────────────────────────────────────

def _is_hallucination(text: str) -> bool:
    norm = re.sub(r"[^\w\s]", "", text).strip().lower()
    if not norm:
        return True
    if norm in _HALLUC_LOOKUP:
        return True
    # Catch cascades where the same long phrase repeats inside one segment.
    for phrase in _HALLUC_LOOKUP:
        if phrase and len(phrase) > 8 and norm.count(phrase) >= 2:
            return True
    return False


def _clean_segments(segments: list[dict]) -> list[dict]:
    """Strip hallucinations + immediate repeats."""
    cleaned = []
    last_text = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text or _is_hallucination(text):
            continue
        norm = re.sub(r"\s+", " ", text.lower())
        if norm == last_text:
            continue  # skip immediate repeat
        last_text = norm
        cleaned.append(seg)
    return cleaned


def _shift_segments(segments: list[dict], offset: float) -> list[dict]:
    """Shift segment + word timestamps by `offset` seconds (for chunked audio)."""
    out = []
    for seg in segments:
        shifted = dict(seg)
        if "start" in shifted:
            shifted["start"] = shifted["start"] + offset
        if "end" in shifted:
            shifted["end"] = shifted["end"] + offset
        if shifted.get("words"):
            shifted["words"] = [
                {**w,
                 "start": w.get("start", 0) + offset,
                 "end": w.get("end", 0) + offset}
                for w in shifted["words"]
            ]
        out.append(shifted)
    return out


# ── Main entry point ──────────────────────────────────────────────────

def transcribe(file_path: str,
               language: Optional[str] = None,
               on_progress: Optional[Callable] = None,
               trim_silence: bool = True) -> dict:
    """
    Transcribe an audio file locally (mlx-whisper or faster-whisper).

    Args:
        file_path: Path to the audio file.
        language: Language code (e.g. 'ro', 'en'), or None for auto-detect.
        on_progress: Callback fn(stage, detail, percent).
        trim_silence: Drop silences in ffmpeg preprocessing. Disable when
            timestamps must align with the original timeline (for diarization).

    Returns:
        {text, segments, language}
    """
    def emit(stage, detail, percent=None):
        if on_progress:
            on_progress(stage, detail, percent)
        log.info("[%s] %s%s", stage, detail,
                 f" ({percent}%)" if percent is not None else "")

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    emit("info", f"File size: {file_size_mb:.1f} MB")

    duration = get_audio_duration(file_path)
    emit("info", f"Duration: {duration / 60:.1f} minutes")

    all_segments: list[dict] = []
    detected_lang = language

    if duration > config.CHUNK_THRESHOLD_MIN * 60:
        action = "Trimming silence + splitting" if trim_silence else "Splitting"
        emit("splitting", f"{action} into {config.CHUNK_MINUTES}-minute chunks...", 5)
        chunks = split_audio(file_path,
                             chunk_minutes=config.CHUNK_MINUTES,
                             trim_silence=trim_silence)
        total_chunks = len(chunks)
        emit("splitting", f"Created {total_chunks} chunks", 10)

        for i, chunk_path in enumerate(chunks):
            chunk_mb = os.path.getsize(chunk_path) / (1024 * 1024)
            pct = 10 + int((i / total_chunks) * 60)  # transcription spans 10→70
            emit("transcribing",
                 f"Chunk {i+1}/{total_chunks} ({chunk_mb:.1f} MB)...", pct)

            start = time.time()
            result = _run_whisper(chunk_path, language)
            elapsed = time.time() - start

            if not detected_lang:
                detected_lang = result.get("language")

            offset = i * config.CHUNK_MINUTES * 60
            segs = _shift_segments(result.get("segments", []), offset)
            segs = _clean_segments(segs)
            all_segments.extend(segs)

            words = sum(len((s.get("text") or "").split()) for s in segs)
            pct_done = 10 + int(((i + 1) / total_chunks) * 60)
            emit("transcribing",
                 f"Chunk {i+1}/{total_chunks} done — {words} words in {elapsed:.0f}s",
                 pct_done)

            try:
                os.unlink(chunk_path)
            except OSError:
                pass

        try:
            os.rmdir(os.path.dirname(chunks[0]))
        except (OSError, IndexError):
            pass

    else:
        action = "Trimming silence + transcribing" if trim_silence else "Transcribing"
        emit("transcribing", f"{action}...", 15)
        pre_path = preprocess_short(file_path, trim_silence=trim_silence)
        start = time.time()
        result = _run_whisper(pre_path, language)
        elapsed = time.time() - start
        if not detected_lang:
            detected_lang = result.get("language")
        all_segments.extend(_clean_segments(result.get("segments", [])))
        emit("transcribing", f"Done in {elapsed:.0f}s", 70)

        try:
            os.unlink(pre_path)
            os.rmdir(os.path.dirname(pre_path))
        except OSError:
            pass

    text = " ".join((s.get("text") or "").strip() for s in all_segments).strip()
    text = re.sub(r"\s+", " ", text)

    emit("transcription_done",
         f"Transcription complete — {len(text.split())} words total", 72)

    return {
        "text": text,
        "segments": all_segments,
        "language": detected_lang,
    }
