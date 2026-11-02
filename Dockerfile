# Meeting Transcriber for the home server (linux/amd64, CPU).
# Uses faster-whisper instead of mlx-whisper, which runs only on Apple Silicon.
#
# Build:  docker build -t meeting-transcriber .
#         docker build --build-arg WITH_DIARIZATION=0 -t meeting-transcriber .   (no speaker labels, ~1.5 GB smaller)
# Run:    docker run --env-file .env -v mt_data:/data -v mt_models:/models -p 127.0.0.1:5001:5001 meeting-transcriber
FROM python:3.13.18-slim-trixie

# ffmpeg: the command-line tool splits and cleans the audio; its libraries are
# what pyannote (speaker labels) uses to read audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MS_ENGINE=faster-whisper \
    MS_HOST=0.0.0.0 \
    MS_PORT=5001 \
    MS_DATA_DIR=/data \
    HF_HOME=/models \
    ALLOW_SHUTDOWN=0

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Speaker labels (pyannote) need PyTorch. The CPU-only build is ~2 GB smaller
# than the default one, which bundles NVIDIA libraries the server can't use.
ARG WITH_DIARIZATION=1
RUN if [ "$WITH_DIARIZATION" = "1" ]; then \
      pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio \
      && pip install "pyannote.audio>=4,<5"; \
    fi

COPY *.py ./
COPY templates ./templates
COPY static ./static

# Ordinary user, not root. /data holds jobs.db and uploads; /models holds the
# downloaded Whisper and pyannote models, so they survive rebuilds.
RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /data /models \
    && chown appuser:appuser /data /models
USER appuser
VOLUME ["/data", "/models"]

EXPOSE 5001

# The first start downloads Whisper large-v3 (~3 GB), so allow plenty of time.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/healthz', timeout=4)"

# One worker: jobs run one at a time. --timeout 0: long transcriptions must not
# be killed. Threads let the page poll for progress while a job runs.
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5001", "--timeout", "0", "wsgi:app"]
