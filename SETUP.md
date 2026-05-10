# Setup — что нужно настроить перед запуском

Бот хранит все секреты в `.env` (скопируй из `.env.example`). Ниже — как получить каждое значение.

## 1. Telegram бот

1. Открой Telegram, найди [@BotFather](https://t.me/BotFather).
2. `/newbot` → имя бота → username (должен заканчиваться на `bot`).
3. Скопируй токен вида `123456789:AAH...` → положи в `.env` как `TELEGRAM_BOT_TOKEN`.

## 2. Свой Telegram ID (для whitelist)

1. Найди в Telegram бота [@userinfobot](https://t.me/userinfobot).
2. Напиши ему `/start` — он пришлёт твой числовой ID.
3. Положи в `.env` как `ADMIN_IDS=123456789` (несколько админов через запятую).

> Также можно запустить бота, написать ему любую команду — он ответит «доступ закрыт» и покажет твой ID.

## 3. OpenAI API

У тебя уже есть ключ. Если нужно создать новый:

1. <https://platform.openai.com/api-keys> → Create new secret key.
2. Положи в `.env` как `OPENAI_API_KEY`.
3. Модель по умолчанию — `gpt-4o-mini` (быстрая и дешёвая, ~$0.0001 за письмо). Можно поменять на `gpt-4o` для качества.

## 4. Yandex SMTP — пароль приложения

**Важно:** обычный пароль от Yandex-почты для SMTP не подойдёт.

1. <https://id.yandex.ru/security/app-passwords>
2. Создать пароль приложения → выбрать «Почта» (IMAP/POP3/SMTP).
3. Скопировать сгенерированный 16-символьный пароль → положить в `.env` как `SMTP_PASSWORD`.
4. В `SMTP_USER` указать **полный** адрес: `you@yandex.ru`.

Также убедись, что в настройках почты:
- Настройки → Почтовые программы → включён «доступ по протоколу SMTP с паролями приложений».

Лимит для обычной Yandex-почты: ~150 писем/сутки (для домена в Yandex 360 — выше). Для 100 получателей с задержкой 2 сек — ~3.5 минуты на рассылку.

## 5. Google Sheets — Service Account

Боту нужен JSON-ключ сервисного аккаунта, чтобы читать и писать в твою таблицу.

### 5.1 Создать проект и сервисный аккаунт

1. <https://console.cloud.google.com/> → создать новый проект (название любое, напр. `email-bot`).
2. APIs & Services → Library → найти **Google Sheets API** → Enable.
3. Там же включить **Google Drive API**.
4. APIs & Services → Credentials → Create credentials → Service account.
5. Имя любое, роль не обязательна → Done.
6. Кликнуть на созданный сервис-аккаунт → вкладка **Keys** → Add key → Create new key → JSON → скачать.
7. Положить файл в корень проекта как `google-creds.json` (или указать другой путь в `GOOGLE_CREDS_FILE`).

### 5.2 Дать сервисному аккаунту доступ к таблице

1. Открой JSON-файл, найди поле `client_email` (что-то вроде `email-bot@your-project.iam.gserviceaccount.com`).
2. Открой свою Google-таблицу → кнопка **Share** → вставь этот email → права **Editor** → Send.

### 5.3 Узнать ID таблицы и лист

URL таблицы: `https://docs.google.com/spreadsheets/d/`<b>`1AbCdEf...XyZ`</b>`/edit` — то, что между `/d/` и `/edit`.

Положи в `.env`:
```
GOOGLE_SHEET_ID=1AbCdEf...XyZ
GOOGLE_SHEET_NAME=Sheet1   # или «Лист1» для русской таблицы
```

### 5.4 Структура таблицы

Минимально нужны две колонки в первой строке (заголовки):

| email | name |
|-|-|
| ivan@example.com | Иван |
| anna@example.com | Анна |

Дополнительно бот *автоматически* добавит при первом запуске рассылки три служебные колонки:
- `unsubscribed` — вручную поставь `1`/`true`, чтобы исключить клиента из рассылок.
- `last_sent_at` — туда бот пишет дату/время отправки.
- `last_status` — туда пишется `ok` или текст ошибки.

Любые другие колонки (например, `company`, `last_purchase`, `segment`) попадут в GPT как контекст для персонализации — добавляй смело.

## 6. Запуск

```bash
cd /Users/iljuha.alikingmail.com/Code/email_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # потом отредактируй
python bot.py
```

В Telegram:
- `/start` — приветствие и список команд.
- `/new` — начать новую рассылку.
- `/cancel` — сбросить черновик.
- `/whoami` — показать свой Telegram ID.
