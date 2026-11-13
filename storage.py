"""
SQLite-backed job storage.

Jobs survive process restarts and the user can list their history. All
writes go through a module-level lock — SQLite's own locking is fine for
our low write volume, but the lock keeps cross-thread access predictable.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_DB_LOCK = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,           -- queued | running | done | error
    stage TEXT,                     -- upload | transcribing | diarizing | cleaning | done | error
    percent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    filename TEXT,
    duration_min REAL,
    word_count INTEGER,
    language TEXT,
    diarized INTEGER DEFAULT 0,
    cleaned INTEGER DEFAULT 0,
    transcript TEXT,
    error TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    log_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


@dataclass
class Job:
    id: str
    status: str = "queued"
    stage: str = "upload"
    percent: int = 0
    created_at: str = ""
    updated_at: str = ""
    filename: Optional[str] = None
    duration_min: Optional[float] = None
    word_count: Optional[int] = None
    language: Optional[str] = None
    diarized: bool = False
    cleaned: bool = False
    transcript: Optional[str] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "filename": self.filename,
            "duration_min": self.duration_min,
            "word_count": self.word_count,
            "language": self.language,
            "diarized": self.diarized,
            "cleaned": self.cleaned,
            "transcript": self.transcript,
            "error": self.error,
            "warnings": list(self.warnings),
            "log": list(self.log),
            "options": dict(self.options),
        }


class JobStore:
    """Thread-safe SQLite job store."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        with _DB_LOCK:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ── Mutations ──────────────────────────────────────────────────

    def create(self, job_id: str, filename: str, options: dict) -> Job:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs (id, status, stage, percent, created_at, "
                "updated_at, filename, options_json) "
                "VALUES (?, 'queued', 'upload', 0, ?, ?, ?, ?)",
                (job_id, now, now, filename, json.dumps(options)),
            )
        return self.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        # Coerce bools so SQLite stores them as ints
        for k in ("diarized", "cleaned"):
            if k in fields:
                fields[k] = 1 if fields[k] else 0
        fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
        keys = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [job_id]
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {keys} WHERE id = ?", values)

    def append_log(self, job_id: str, entry: dict) -> None:
        with self._conn() as c:
            row = c.execute(
                "SELECT log_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return
            log = json.loads(row["log_json"])
            log.append(entry)
            c.execute(
                "UPDATE jobs SET log_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(log),
                 datetime.now().isoformat(timespec="seconds"),
                 job_id),
            )

    def append_warning(self, job_id: str, message: str) -> None:
        with self._conn() as c:
            row = c.execute(
                "SELECT warnings_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return
            warnings = json.loads(row["warnings_json"])
            warnings.append(message)
            c.execute(
                "UPDATE jobs SET warnings_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(warnings),
                 datetime.now().isoformat(timespec="seconds"),
                 job_id),
            )

    def reconcile_interrupted(self) -> int:
        """
        Mark jobs left at 'queued'/'running' by a previous process as errored.

        A row becomes 'running' when its worker takes the pipeline slot, and
        only that same thread moves it to 'done'/'error'. A crash, restart or
        redeploy therefore strands it at 'running' forever, where the UI shows
        it as live and it can never be cleared. Called once at startup, when
        by definition no job of this process can be in flight yet.

        Returns the number of rows fixed.
        """
        with self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status = 'error', stage = 'error', "
                "error = ?, updated_at = ? "
                "WHERE status IN ('queued', 'running')",
                ("Interrupted by a server restart — please run it again.",
                 datetime.now().isoformat(timespec="seconds")),
            )
            return cur.rowcount

    # ── Reads ──────────────────────────────────────────────────────

    def get(self, job_id: str) -> Optional[Job]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_recent(self, limit: int = 50) -> list[Job]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def queue_depth(self) -> int:
        """How many jobs are queued or running right now."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM jobs "
                "WHERE status IN ('queued', 'running')"
            ).fetchone()
        return row["n"]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            status=row["status"],
            stage=row["stage"],
            percent=row["percent"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            filename=row["filename"],
            duration_min=row["duration_min"],
            word_count=row["word_count"],
            language=row["language"],
            diarized=bool(row["diarized"]),
            cleaned=bool(row["cleaned"]),
            transcript=row["transcript"],
            error=row["error"],
            warnings=json.loads(row["warnings_json"] or "[]"),
            log=json.loads(row["log_json"] or "[]"),
            options=json.loads(row["options_json"] or "{}"),
        )
