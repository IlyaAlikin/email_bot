from __future__ import annotations

import asyncio
import html
import logging
import re
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
    editing_brief = State()
    editing_body = State()


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Campaign.waiting_subject)
    await message.answer(
        "📨 <b>Новая рассылка — шаг 1/4</b>\n\n"
        "Введи <b>тему письма</b> (Subject). Это то, что увидит клиент в ящике до открытия.\n\n"
        "Например: <i>Оптовая печать: −20% до конца недели</i>"
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
        "Например: <i>Предложение по оптовой печати визиток, листовок и баннеров. "
        "Скидка 20% на первый заказ при оформлении до конца месяца. "
        "Тон деловой, обращение на «вы». Подписать как «команда типографии Форвард-С».</i>"
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

    sample = active[0]
    await state.update_data(
        total=len(active),
        unsubscribed_count=len(recipients) - len(active),
        sample_email=sample.email,
        sample_name=sample.name,
        sample_extra=sample.extra,
    )
    await state.set_state(Campaign.waiting_confirm)
    await _render_preview(progress, state, gpt, edit=True)


async def _render_preview(
    message: Message,
    state: FSMContext,
    gpt: GPTPersonalizer,
    *,
    edit: bool,
    note: str = "",
) -> None:
    """Build preview for the first recipient and show confirm keyboard.

    edit=True → редактировать переданное сообщение; edit=False → отправить новое.
    """
    data = await state.get_data()
    subject: str = data["subject"]
    brief: str = data["brief"]
    manual_body: str | None = data.get("manual_body")
    attachments = data.get("attachments", [])
    total: int = data["total"]
    unsubscribed_count: int = data.get("unsubscribed_count", 0)

    sample = Recipient(
        row_index=0,
        email=data["sample_email"],
        name=data["sample_name"],
        extra=dict(data.get("sample_extra") or {}),
    )

    progress_text = "⏳ Генерирую превью на первом клиенте…"
    if edit:
        try:
            await message.edit_text(progress_text)
        except Exception:
            pass

    if manual_body is not None:
        body = _safe_format(manual_body, _recipient_mapping(sample))
        mode_label = "📝 Ручной шаблон (без GPT) — поддерживает плейсхолдеры {name}, {company}, …"
    else:
        try:
            body = await gpt.generate_body(subject=subject, brief=brief, recipient=sample)
        except Exception as exc:
            log.exception("GPT preview failed")
            err_text = (
                f"❌ GPT вернул ошибку:\n<code>{html.escape(str(exc))}</code>\n\n"
                "Возможно, OpenAI медленно отвечает или сеть прервалась. Попробуй ещё раз."
            )
            if edit:
                await message.edit_text(err_text, reply_markup=_retry_kb())
            else:
                await message.answer(err_text, reply_markup=_retry_kb())
            return
        mode_label = "🤖 GPT персонализирует под каждого клиента"

    preview_text = (
        "📨 <b>Шаг 4/4 — превью и подтверждение</b>\n\n"
        f"<b>Тема:</b> {html.escape(subject)}\n"
        f"<b>Получателей:</b> {total}"
        + (f" (отписалось: {unsubscribed_count})" if unsubscribed_count else "")
        + f"\n<b>Вложений:</b> {len(attachments)}\n"
        f"<b>Режим:</b> {mode_label}\n"
        f"<b>Пример (для {html.escape(sample.name)} &lt;{html.escape(sample.email)}&gt;):</b>\n\n"
        f"<pre>{html.escape(body)}</pre>"
    )
    if note:
        preview_text += f"\n\n<i>{html.escape(note)}</i>"

    if edit:
        await message.edit_text(preview_text, reply_markup=_confirm_kb())
    else:
        await message.answer(preview_text, reply_markup=_confirm_kb())


@router.callback_query(Campaign.waiting_confirm, F.data == "send:cancel")
async def confirm_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Отменено")
    if call.message:
        await call.message.edit_text("❌ Рассылка отменена. /new чтобы начать заново.")
    await state.clear()


@router.callback_query(Campaign.waiting_confirm, F.data == "send:regen")
async def confirm_regen(
    call: CallbackQuery,
    state: FSMContext,
    gpt: GPTPersonalizer,
    **_: object,
) -> None:
    await call.answer("Перегенерирую…")
    if call.message is None:
        return
    # Сбросим manual_body — regen всегда про GPT.
    await state.update_data(manual_body=None)
    await _render_preview(call.message, state, gpt, edit=True, note="Перегенерировано.")


@router.callback_query(Campaign.waiting_confirm, F.data == "send:edit_brief")
async def confirm_edit_brief(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message is None:
        return
    await state.set_state(Campaign.editing_brief)
    await call.message.edit_text(
        "✏️ <b>Новый бриф для GPT</b>\n\n"
        "Введи обновлённое описание письма. После — сразу обновлю превью.\n\n"
        "Чтобы отказаться — /cancel."
    )


@router.message(Campaign.editing_brief, F.text)
async def edit_brief_apply(
    message: Message,
    state: FSMContext,
    gpt: GPTPersonalizer,
    **_: object,
) -> None:
    new_brief = (message.text or "").strip()
    if len(new_brief) < 10:
        await message.answer("Бриф слишком короткий — добавь деталей.")
        return
    await state.update_data(brief=new_brief, manual_body=None)
    await state.set_state(Campaign.waiting_confirm)
    await _render_preview(message, state, gpt, edit=False, note="Бриф обновлён.")


@router.callback_query(Campaign.waiting_confirm, F.data == "send:manual")
async def confirm_manual(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message is None:
        return
    await state.set_state(Campaign.editing_body)
    await call.message.edit_text(
        "📝 <b>Свой текст письма</b>\n\n"
        "Вставь готовое тело письма. GPT вызываться не будет — каждому уйдёт твой текст с подстановкой плейсхолдеров.\n\n"
        "Поддерживаются плейсхолдеры по колонкам таблицы:\n"
        "  • <code>{name}</code> — имя клиента\n"
        "  • <code>{email}</code> — почта\n"
        "  • <code>{company}</code> и любые другие колонки\n\n"
        "Если плейсхолдер не найден в таблице — он останется в тексте как есть.\n\n"
        "Чтобы вернуться к GPT-режиму — /cancel и начни заново /new."
    )


@router.message(Campaign.editing_body, F.text)
async def edit_body_apply(
    message: Message,
    state: FSMContext,
    gpt: GPTPersonalizer,
    **_: object,
) -> None:
    body = (message.text or "").strip()
    if len(body) < 20:
        await message.answer("Текст слишком короткий — пришли полное тело письма.")
        return
    await state.update_data(manual_body=body)
    await state.set_state(Campaign.waiting_confirm)
    await _render_preview(message, state, gpt, edit=False, note="Загружен ручной шаблон.")


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
    manual_body: str | None = data.get("manual_body")
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
            if manual_body is not None:
                body = _safe_format(manual_body, _recipient_mapping(recipient))
            else:
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


def _retry_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="send:regen")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="send:cancel")],
        ]
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Отправить всем", callback_data="send:go")],
            [
                InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="send:regen"),
                InlineKeyboardButton(text="✏️ Изменить бриф", callback_data="send:edit_brief"),
            ],
            [InlineKeyboardButton(text="📝 Свой текст", callback_data="send:manual")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="send:cancel")],
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


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _safe_format(template: str, mapping: dict[str, str]) -> str:
    """Substitute {key} placeholders from mapping, leave unknowns intact."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return mapping.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(repl, template)


def _recipient_mapping(recipient: Recipient) -> dict[str, str]:
    mapping: dict[str, str] = {"name": recipient.name, "email": recipient.email}
    for k, v in recipient.extra.items():
        mapping[k.lower()] = v
    return mapping
