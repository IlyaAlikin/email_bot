from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_IDS", "")
    ids = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    return frozenset(int(x) for x in ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]

    openai_api_key: str
    openai_model: str

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from_name: str

    # Google Sheets (optional — falls back to CSV if sheet_id is empty)
    google_creds_file: Path
    google_sheet_id: str
    google_sheet_name: str

    # CSV fallback
    recipients_csv: Path

    send_delay_seconds: float
    attachments_dir: Path

    @property
    def use_csv(self) -> bool:
        return not self.google_sheet_id


def load_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent
    attachments_dir = base_dir / "attachments"
    attachments_dir.mkdir(exist_ok=True)

    return Settings(
        bot_token=_required("TELEGRAM_BOT_TOKEN"),
        admin_ids=_admin_ids(),
        openai_api_key=_required("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.yandex.ru"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=_required("SMTP_USER"),
        smtp_password=_required("SMTP_PASSWORD"),
        smtp_from_name=os.getenv("SMTP_FROM_NAME", ""),
        google_creds_file=Path(os.getenv("GOOGLE_CREDS_FILE", "./google-creds.json")).expanduser().resolve(),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
        google_sheet_name=os.getenv("GOOGLE_SHEET_NAME", "Sheet1"),
        recipients_csv=(base_dir / os.getenv("RECIPIENTS_CSV", "recipients.csv")).resolve(),
        send_delay_seconds=float(os.getenv("SEND_DELAY_SECONDS", "2")),
        attachments_dir=attachments_dir,
    )
