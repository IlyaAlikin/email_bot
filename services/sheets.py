from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

REQUIRED_COLS = ("email", "name")
STATUS_COLS = ("unsubscribed", "last_sent_at", "last_status")


@dataclass
class Recipient:
    row_index: int  # 1-based; row 1 is header, so data starts at 2
    email: str
    name: str
    extra: dict[str, str] = field(default_factory=dict)
    unsubscribed: bool = False


class SheetsService:
    def __init__(self, creds_file: Path, sheet_id: str, sheet_name: str) -> None:
        self._creds_file = creds_file
        self._sheet_id = sheet_id
        self._sheet_name = sheet_name
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None

    def _connect_sync(self) -> gspread.Worksheet:
        if self._worksheet is not None:
            return self._worksheet
        creds = Credentials.from_service_account_file(str(self._creds_file), scopes=SCOPES)
        self._client = gspread.authorize(creds)
        spreadsheet = self._client.open_by_key(self._sheet_id)
        self._worksheet = spreadsheet.worksheet(self._sheet_name)
        return self._worksheet

    async def _connect(self) -> gspread.Worksheet:
        return await asyncio.to_thread(self._connect_sync)

    async def fetch_recipients(self) -> list[Recipient]:
        ws = await self._connect()
        records = await asyncio.to_thread(ws.get_all_records)
        if records:
            await asyncio.to_thread(self._ensure_status_columns, ws, list(records[0].keys()))
        return [self._row_to_recipient(idx, row) for idx, row in enumerate(records, start=2)]

    @staticmethod
    def _row_to_recipient(row_index: int, row: dict[str, Any]) -> Recipient:
        normalized = {k.strip().lower(): str(v).strip() for k, v in row.items()}
        email = normalized.get("email", "")
        name = normalized.get("name", "")
        unsubscribed = normalized.get("unsubscribed", "").lower() in {"1", "true", "yes", "y", "да", "x"}
        extra = {
            k: v
            for k, v in normalized.items()
            if k not in {"email", "name", "unsubscribed", "last_sent_at", "last_status"} and v
        }
        return Recipient(row_index=row_index, email=email, name=name, extra=extra, unsubscribed=unsubscribed)

    def _ensure_status_columns(self, ws: gspread.Worksheet, header: list[str]) -> None:
        header_lower = [h.strip().lower() for h in header]
        missing = [c for c in STATUS_COLS if c not in header_lower]
        if not missing:
            return
        start_col = len(header) + 1
        cell_range = gspread.utils.rowcol_to_a1(1, start_col) + ":" + gspread.utils.rowcol_to_a1(1, start_col + len(missing) - 1)
        ws.update(values=[missing], range_name=cell_range)

    async def mark_sent(self, row_index: int, status: str) -> None:
        ws = await self._connect()
        header = await asyncio.to_thread(ws.row_values, 1)
        header_lower = [h.strip().lower() for h in header]
        try:
            ts_col = header_lower.index("last_sent_at") + 1
            status_col = header_lower.index("last_status") + 1
        except ValueError:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await asyncio.to_thread(ws.update_cell, row_index, ts_col, timestamp)
        await asyncio.to_thread(ws.update_cell, row_index, status_col, status)

    @staticmethod
    def validate_required_columns(recipients: list[Recipient]) -> str | None:
        """Return error message if required columns are missing, else None."""
        if not recipients:
            return "Таблица пустая — добавь хотя бы одну строку с email и name."
        sample = recipients[0]
        if not sample.email:
            return "В таблице нет колонки `email` (или она пустая в первой строке). Добавь колонку `email`."
        if not sample.name:
            return "В таблице нет колонки `name` (или она пустая в первой строке). Добавь колонку `name`."
        return None
