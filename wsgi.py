"""
Production entrypoint for gunicorn / waitress / any WSGI server.

Example:
    gunicorn -w 1 -b 0.0.0.0:5001 --timeout 0 wsgi:app

Notes:
- Use ONE worker. The pipeline already serializes jobs via a module lock;
  a second worker would just be wasted memory and the queue wouldn't be
  shared between them.
- --timeout 0 disables gunicorn's default 30s worker timeout (transcribing
  a 2-hour meeting takes much longer than 30s).
- For HTTPS / multi-user, put a real reverse proxy (nginx, caddy) in front.
"""

import logging

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

from app import app  # noqa: E402,F401  (gunicorn imports `app`)

# Eagerly warm up the model so the first request doesn't pay the cost.
from transcriber import preload_model  # noqa: E402
preload_model()
