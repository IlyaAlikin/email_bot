from __future__ import annotations

import asyncio
import csv
from datetime import datetime
from pathlib import Path

from services.sheets import Recipient

REQUIRED_COLS = ("email", "name")
STATUS_COLS = ("unsubscribed", "last_sent_at", "last_status")


class CSVSource:
    """CSV-based fallback so the bot can run without Google Sheets credentials.

    Writes status updates back to the same file by rewriting it.
    """

    def __init__(self, csv_path: Path) -> None:
        self._path = csv_path
        self._lock = asyncio.Lock()

    async def fetch_recipients(self) -> list[Recipient]:
        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> list[Recipient]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        recipients: list[Recipient] = []
        for idx, row in enumerate(rows, start=2):
            normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            email = normalized.get("email", "")
            name = normalized.get("name", "")
            unsubscribed = normalized.get("unsubscribed", "").lower() in {"1", "true", "yes", "y", "да", "x"}
            extra = {
                k: v
                for k, v in normalized.items()
                if k not in {"email", "name", "unsubscribed", "last_sent_at", "last_status"} and v
            }
            recipients.append(
                Recipient(row_index=idx, email=email, name=name, extra=extra, unsubscribed=unsubscribed)
            )
        return recipients

    async def mark_sent(self, row_index: int, status: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_status_sync, row_index, status)

    def _write_status_sync(self, row_index: int, status: str) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        if not rows:
            return

        header = [h.strip() for h in rows[0]]
        header_lower = [h.lower() for h in header]
        for col in STATUS_COLS:
            if col not in header_lower:
                header.append(col)
                header_lower.append(col)
                for r in rows[1:]:
                    r.append("")
        rows[0] = header

        ts_idx = header_lower.index("last_sent_at")
        st_idx = header_lower.index("last_status")
        target = row_index - 1  # rows[0] is header; row_index 2 → rows[1]
        if 0 < target < len(rows):
            while len(rows[target]) < len(header):
                rows[target].append("")
            rows[target][ts_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows[target][st_idx] = status

        with self._path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows)
