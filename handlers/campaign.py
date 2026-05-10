from __future__ import annotations

import asyncio
import html
import logging
import uuid
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import Settings
from services.csv_source import CSVSource
from services.gpt import GPTPersonalizer
from services.mailer import Attachment, Mailer
from services.sheets import Recipient, SheetsService

RecipientsSource = SheetsService | CSVSource

log = logging.getLogger(__name__)

router = Router(name="campaign")


class Campaign(StatesGroup):
    waiting_subject = State()
    waiting_brief = State()
    waiting_attachments = State()
    waiting_confirm = State()


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Campaign.waiting_subject)
    await message.answer(
        "📨 <b>Новая рассылка — шаг 1/4</b>\n\n"
        "Введи <b>тему письма</b> (Subject). Это то, что увидит клиент в ящике до открытия.\n\n"
        "Например: <i>Летняя коллекция Estelle: −20% до конца недели</i>"
    )


@router.message(Campaign.waiting_subject, F.text)
async def step_subject(message: Message, state: FSMContext) -> None:
    subject = (message.text or "").strip()
    if len(subject) < 3:
        await message.answer("Слишком короткая тема. Введи нормальный Subject.")
        return
    if len(subject) > 200:
        await message.answer("Тема слишком длинная — не больше 200 символов.")
        return
    await state.update_data(subject=subject, attachments=[])
    await state.set_state(Campaign.waiting_brief)
    await message.answer(
        "✏️ <b>Шаг 2/4 — бриф для GPT</b>\n\n"
        "Опиши <b>что должно быть в письме</b>: повод, оффер, дедлайн, нужный тон.\n"
        "GPT адаптирует это под каждого клиента (имя, доп. поля из таблицы).\n\n"
        "Например: <i>Анонс летней коллекции, скидка 20% по промокоду SUMMER до 31 июля. "
        "Тон тёплый, обращение на «вы». Подписать как «команда Estelle».</i>"
    )


@router.message(Campaign.waiting_brief, F.text)
async def step_brief(message: Message, state: FSMContext) -> None:
    brief = (message.text or "").strip()
    if len(brief) < 10:
        await message.answer("Бриф слишком короткий — добавь деталей.")
        return
    await state.update_data(brief=brief)
    await state.set_state(Campaign.waiting_attachments)
    await message.answer(
        "📎 <b>Шаг 3/4 — вложения</b>\n\n"
        "Пришли файлы (документы, картинки), которые нужно прикрепить ко всем письмам. "
        "Можно несколько по одному.\n\n"
        "Когда закончишь — нажми кнопку ниже или отправь /skip, если вложений нет.",
        reply_markup=_attachments_done_kb(),
    )


@router.message(Campaign.waiting_attachments, Command("skip"))
async def step_skip_attachments(message: Message, state: FSMContext, **kw) -> None:
    await _go_to_confirm(message, state, **kw)


@router.callback_query(Campaign.waiting_attachments, F.data == "att:done")
async def step_attachments_done(call: CallbackQuery, state: FSMContext, **kw) -> None:
    if call.message is None:
        return
    await call.answer()
    await _go_to_confirm(call.message, state, **kw)


@router.message(Campaign.waiting_attachments, F.document | F.photo)
async def step_attachments_collect(
    message: Message,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
) -> None:
    file_id, filename = _extract_file(message)
    if file_id is None:
        await message.answer("Не получилось распознать файл. Пришли как документ.")
        return

    file = await bot.get_file(file_id)
    if file.file_path is None:
        await message.answer("Не удалось получить путь к файлу в Telegram. Попробуй ещё раз.")
        return

    local_name = f"{uuid.uuid4().hex}_{filename}"
    local_path = settings.attachments_dir / local_name
    await bot.download_file(file.file_path, destination=local_path)

    data = await state.get_data()
    attachments = list(data.get("attachments", []))
    attachments.append({"filename": filename, "path": str(local_path)})
    await state.update_data(attachments=attachments)

    await message.answer(
        f"✅ Прикреплено: <b>{html.escape(filename)}</b> (всего: {len(attachments)})",
        reply_markup=_attachments_done_kb(),
    )


async def _go_to_confirm(
    message: Message,
    state: FSMContext,
    sheets: RecipientsSource,
    gpt: GPTPersonalizer,
    **_: object,
) -> None:
    data = await state.get_data()
    subject = data["subject"]
    brief = data["brief"]
    attachments = data.get("attachments", [])

    progress = await message.answer("⏳ Тяну базу клиентов из Google Sheets…")

    try:
        recipients = await sheets.fetch_recipients()
    except Exception as exc:
        log.exception("Failed to fetch recipients")
        await progress.edit_text(
            f"❌ Не удалось прочитать таблицу.\n<code>{html.escape(str(exc))}</code>\n\n"
            "Проверь GOOGLE_SHEET_ID и что Service Account email добавлен в шаринг таблицы как редактор."
        )
        await state.clear()
        return

    err = SheetsService.validate_required_columns(recipients)
    if err:
        await progress.edit_text(f"⚠️ {err}")
        await state.clear()
        return

    active = [r for r in recipients if not r.unsubscribed and r.email]
    if not active:
        await progress.edit_text("В базе нет активных получателей (все unsubscribed или без email).")
        await state.clear()
        return

    await progress.edit_text(
        f"✅ Найдено получателей: <b>{len(active)}</b>"
        + (f" (отписалось: {len(recipients) - len(active)})" if len(active) != len(recipients) else "")
        + "\n\n⏳ Генерирую превью на первом клиенте…"
    )

    sample = active[0]
    try:
        preview_body = await gpt.generate_body(subject=subject, brief=brief, recipient=sample)
    except Exception as exc:
        log.exception("GPT preview failed")
        await progress.edit_text(
            f"❌ GPT вернул ошибку при генерации превью:\n<code>{html.escape(str(exc))}</code>"
        )
        await state.clear()
        return

    await state.update_data(total=len(active))
    await state.set_state(Campaign.waiting_confirm)

    preview_text = (
        "📨 <b>Шаг 4/4 — превью и подтверждение</b>\n\n"
        f"<b>Тема:</b> {html.escape(subject)}\n"
        f"<b>Получателей:</b> {len(active)}\n"
        f"<b>Вложений:</b> {len(attachments)}\n"
        f"<b>Пример (для {html.escape(sample.name)} &lt;{html.escape(sample.email)}&gt;):</b>\n\n"
        f"<pre>{html.escape(preview_body)}</pre>\n\n"
        "Каждому клиенту GPT сгенерирует <i>свой</i> вариант. Отправляем?"
    )

    await progress.edit_text(preview_text, reply_markup=_confirm_kb())


@router.callback_query(Campaign.waiting_confirm, F.data == "send:cancel")
async def confirm_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Отменено")
    if call.message:
        await call.message.edit_text("❌ Рассылка отменена. /new чтобы начать заново.")
    await state.clear()


@router.callback_query(Campaign.waiting_confirm, F.data == "send:go")
async def confirm_go(
    call: CallbackQuery,
    state: FSMContext,
    sheets: RecipientsSource,
    gpt: GPTPersonalizer,
    mailer: Mailer,
    settings: Settings,
) -> None:
    await call.answer()
    if call.message is None:
        return

    data = await state.get_data()
    subject: str = data["subject"]
    brief: str = data["brief"]
    raw_attachments = data.get("attachments", [])
    attachments = [Attachment(filename=a["filename"], path=Path(a["path"])) for a in raw_attachments]

    recipients = await sheets.fetch_recipients()
    active = [r for r in recipients if not r.unsubscribed and r.email]
    total = len(active)

    progress_msg = await call.message.edit_text(f"🚀 Стартую рассылку: 0/{total}…")

    sent = 0
    failed = 0
    for idx, recipient in enumerate(active, start=1):
        try:
            body = await gpt.generate_body(subject=subject, brief=brief, recipient=recipient)
            await mailer.send(
                to_email=recipient.email,
                subject=subject,
                body=body,
                attachments=attachments,
            )
            await sheets.mark_sent(recipient.row_index, "ok")
            sent += 1
        except Exception as exc:
            failed += 1
            log.exception("Failed to send to %s", recipient.email)
            try:
                await sheets.mark_sent(recipient.row_index, f"error: {exc}"[:200])
            except Exception:
                pass

        if idx % 5 == 0 or idx == total:
            try:
                await progress_msg.edit_text(
                    f"📤 Отправка: {idx}/{total}\n✅ {sent}   ❌ {failed}"
                )
            except Exception:
                pass

        if idx < total:
            await asyncio.sleep(settings.send_delay_seconds)

    _cleanup_attachments(attachments)

    source_label = "CSV" if isinstance(sheets, CSVSource) else "Google Sheets"
    await progress_msg.edit_text(
        f"🏁 <b>Готово</b>\nВсего: {total}\n✅ Успешно: {sent}\n❌ Ошибок: {failed}\n\n"
        f"Статус каждой строки записан в {source_label} (колонки last_sent_at, last_status)."
    )
    await state.clear()


def _attachments_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Готово, без вложений / закончил →", callback_data="att:done")]]
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Отправить всем", callback_data="send:go"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="send:cancel"),
            ]
        ]
    )


def _extract_file(message: Message) -> tuple[str | None, str]:
    if message.document is not None:
        return message.document.file_id, message.document.file_name or "document"
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, f"photo_{photo.file_unique_id}.jpg"
    return None, ""


def _cleanup_attachments(attachments: list[Attachment]) -> None:
    for att in attachments:
        try:
            att.path.unlink(missing_ok=True)
        except Exception:
            pass
