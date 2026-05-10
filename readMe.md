# email_bot

Telegram-бот для email-рассылок по базе клиентов в Google Sheets.
Каждое письмо персонализируется через OpenAI GPT и отправляется через Yandex SMTP.

## Возможности

- Тянет базу клиентов из Google Sheets (минимум: `email`, `name`).
- GPT генерирует уникальное тело письма под каждого клиента (использует все колонки таблицы как контекст).
- Принимает вложения через Telegram и прикрепляет их ко всем письмам.
- Превью на первом клиенте и подтверждение перед массовой отправкой.
- Whitelist админов по Telegram ID.
- Пишет статус каждой отправки обратно в таблицу (`last_sent_at`, `last_status`).
- Пропускает строки с `unsubscribed=1`.

## Поток работы

```
/new → ввести Subject → бриф для GPT → (опц.) вложения →
  превью на первом клиенте → confirm → отправка с прогрессом
```

## Запуск

См. **[SETUP.md](./SETUP.md)** — пошаговая инструкция по получению всех ключей (BotFather, OpenAI, Yandex app password, Google Service Account).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # отредактировать
python bot.py
```

## Стек

- Python 3.11+
- aiogram 3 (FSM, inline-кнопки)
- openai (Chat Completions API)
- gspread + google-auth (Google Sheets)
- aiosmtplib (асинхронный SMTP с TLS)

## Ограничения первой версии

- Без БД — состояние FSM в памяти процесса (если бот упадёт во время рассылки, продолжить нельзя; `last_sent_at` в таблице покажет, до кого дошло).
- Без отправки в фоне — пока идёт рассылка, окошко прогресса в Telegram обновляется, бот живёт в одном процессе.
- Рассчитан на ~100 получателей за раз. Для 1000+ — стоит переехать на SendGrid/Mailgun.
