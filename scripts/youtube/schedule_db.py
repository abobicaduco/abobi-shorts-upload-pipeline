# -*- coding: utf-8 -*-
"""SQLite persistence for YouTube scheduled uploads and slot occupancy.

Publishing policy (Shorts): max 3 per calendar day at hours 16, 18, 21
(America/Sao_Paulo). Enforced by unique (slot_date, slot_hour) occupancy via
is_slot_taken() and daily_slot_occupancy view — see docs/youtube/SCHEDULING_POLICY.md.
Long-form (1/day, separate slot) is planned; not stored in schema yet.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

DEFAULT_DB_PATH = Path.home() / ".secrets" / "youtube_schedule.db"

STATUSES_OCCUPYING = ("pending", "uploading", "scheduled", "uploaded")


@dataclass
class ScheduledRow:
    id: int
    file_path: str
    video_id: Optional[str]
    title: str
    scheduled_at_utc: datetime
    slot_date: str
    slot_hour: int
    status: str
    created_at: datetime
    retry_count: int = 0
    last_error: Optional[str] = None


class ScheduleDB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scheduled_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL UNIQUE,
                    video_id TEXT,
                    title TEXT NOT NULL,
                    scheduled_at_utc TEXT NOT NULL,
                    slot_date TEXT NOT NULL,
                    slot_hour INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_scheduled_slot
                    ON scheduled_uploads(slot_date, slot_hour, status);

                CREATE INDEX IF NOT EXISTS idx_scheduled_status
                    ON scheduled_uploads(status);

                CREATE VIEW IF NOT EXISTS daily_slot_occupancy AS
                SELECT
                    slot_date,
                    MAX(CASE WHEN slot_hour = 16 AND status IN (
                        'pending','uploading','scheduled','uploaded'
                    ) THEN 1 ELSE 0 END) AS hour_16,
                    MAX(CASE WHEN slot_hour = 18 AND status IN (
                        'pending','uploading','scheduled','uploaded'
                    ) THEN 1 ELSE 0 END) AS hour_18,
                    MAX(CASE WHEN slot_hour = 21 AND status IN (
                        'pending','uploading','scheduled','uploaded'
                    ) THEN 1 ELSE 0 END) AS hour_21
                FROM scheduled_uploads
                GROUP BY slot_date;
                """
            )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_dt(raw: str) -> datetime:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def is_slot_taken(self, slot_date: str, slot_hour: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM scheduled_uploads
                WHERE slot_date = ? AND slot_hour = ?
                  AND status IN ('pending','uploading','scheduled','uploaded')
                LIMIT 1
                """,
                (slot_date, slot_hour),
            ).fetchone()
            return row is not None

    def get_occupancy(self, slot_date: str) -> dict[int, bool]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT hour_16, hour_18, hour_21
                FROM daily_slot_occupancy WHERE slot_date = ?
                """,
                (slot_date,),
            ).fetchone()
        if not row:
            return {16: False, 18: False, 21: False}
        return {
            16: bool(row["hour_16"]),
            18: bool(row["hour_18"]),
            21: bool(row["hour_21"]),
        }

    def insert_pending(
        self,
        file_path: Path,
        title: str,
        scheduled_at_utc: datetime,
        slot_date: str,
        slot_hour: int,
    ) -> int:
        now = self._utc_now().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_uploads (
                    file_path, title, scheduled_at_utc, slot_date, slot_hour,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    str(file_path.resolve()),
                    title,
                    scheduled_at_utc.astimezone(timezone.utc).isoformat(),
                    slot_date,
                    slot_hour,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_by_file(self, file_path: Path) -> Optional[ScheduledRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_uploads WHERE file_path = ?",
                (str(file_path.resolve()),),
            ).fetchone()
        return self._row_to_dataclass(row) if row else None

    def list_by_status(self, statuses: Sequence[str]) -> list[ScheduledRow]:
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM scheduled_uploads
                WHERE status IN ({placeholders})
                ORDER BY scheduled_at_utc
                """,
                tuple(statuses),
            ).fetchall()
        return [self._row_to_dataclass(r) for r in rows]

    def mark_uploading(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_uploads SET status = 'uploading' WHERE id = ?",
                (row_id,),
            )

    def mark_scheduled(self, row_id: int, video_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scheduled_uploads
                SET status = 'scheduled', video_id = ?, last_error = NULL
                WHERE id = ?
                """,
                (video_id, row_id),
            )

    def mark_failed(self, row_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scheduled_uploads
                SET status = 'failed', retry_count = retry_count + 1, last_error = ?
                WHERE id = ?
                """,
                (error[:2000], row_id),
            )

    def reset_for_retry(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scheduled_uploads
                SET status = 'pending', last_error = NULL
                WHERE id = ? AND retry_count < 3
                """,
                (row_id,),
            )

    def update_title(self, row_id: int, title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_uploads SET title = ? WHERE id = ?",
                (title[:200], row_id),
            )

    def count_summary(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM scheduled_uploads GROUP BY status"
            ).fetchall()
        return {str(r["status"]): int(r["n"]) for r in rows}

    def _row_to_dataclass(self, row: sqlite3.Row) -> ScheduledRow:
        return ScheduledRow(
            id=int(row["id"]),
            file_path=str(row["file_path"]),
            video_id=row["video_id"],
            title=str(row["title"]),
            scheduled_at_utc=self._parse_dt(str(row["scheduled_at_utc"])),
            slot_date=str(row["slot_date"]),
            slot_hour=int(row["slot_hour"]),
            status=str(row["status"]),
            created_at=self._parse_dt(str(row["created_at"])),
            retry_count=int(row["retry_count"] or 0),
            last_error=row["last_error"],
        )


def default_db_path() -> Path:
    return DEFAULT_DB_PATH
