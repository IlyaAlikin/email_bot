from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_settings
from handlers import campaign, start
from services.auth import AdminOnlyMiddleware
from services.csv_source import CSVSource
from services.gpt import GPTPersonalizer
from services.mailer import Mailer
from services.sheets import SheetsService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("email_bot")


async def main() -> None:
    settings = load_settings()

    log.warning(
        "Whitelist админов ОТКЛЮЧЁН — бот доступен любому, кто знает username. "
        "Включи AdminOnlyMiddleware в bot.py и заполни ADMIN_IDS, когда закончишь тесты."
    )

    if settings.use_csv:
        log.info("Using CSV source: %s", settings.recipients_csv)
        sheets: SheetsService | CSVSource = CSVSource(settings.recipients_csv)
    else:
        log.info("Using Google Sheets source: %s/%s", settings.google_sheet_id, settings.google_sheet_name)
        sheets = SheetsService(
            creds_file=settings.google_creds_file,
            sheet_id=settings.google_sheet_id,
            sheet_name=settings.google_sheet_name,
        )
    gpt = GPTPersonalizer(api_key=settings.openai_api_key, model=settings.openai_model)
    mailer = Mailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        from_name=settings.smtp_from_name,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # NOTE: whitelist временно отключён — бот доступен всем, кто его найдёт.
    # Чтобы включить обратно — раскомментируй три строки и заполни ADMIN_IDS в .env.
    # admin_mw = AdminOnlyMiddleware(settings.admin_ids)
    # dp.message.middleware(admin_mw)
    # dp.callback_query.middleware(admin_mw)

    dp["settings"] = settings
    dp["sheets"] = sheets
    dp["gpt"] = gpt
    dp["mailer"] = mailer

    dp.include_router(start.router)
    dp.include_router(campaign.router)

    log.info("Bot is starting. Whitelisted admins: %s", sorted(settings.admin_ids))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
