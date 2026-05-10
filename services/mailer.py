from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import aiosmtplib


@dataclass
class Attachment:
    filename: str
    path: Path


class Mailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        from_name: str,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_name = from_name

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        attachments: list[Attachment],
    ) -> None:
        msg = EmailMessage()
        msg["From"] = formataddr((self._from_name, self._user)) if self._from_name else self._user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        for att in attachments:
            data = att.path.read_bytes()
            maintype, subtype = _guess_mime(att.filename)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=att.filename)

        await aiosmtplib.send(
            msg,
            hostname=self._host,
            port=self._port,
            username=self._user,
            password=self._password,
            use_tls=True,
        )


def _guess_mime(filename: str) -> tuple[str, str]:
    import mimetypes

    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        main, sub = guessed.split("/", 1)
        return main, sub
    return "application", "octet-stream"
