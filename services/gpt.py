from __future__ import annotations

from openai import AsyncOpenAI

from services.sheets import Recipient

SYSTEM_PROMPT = """Ты — копирайтер email-рассылок. Тебе дают:
1) Тему письма (Subject) — её менять НЕЛЬЗЯ, она задаётся отдельно.
2) Бриф маркетолога — что нужно донести.
3) Данные конкретного клиента: имя и опциональные поля (компания, сегмент и т.п.).

Твоя задача — написать ТЕЛО письма на русском языке от первого лица компании.
Требования:
- Обращение по имени клиента в начале.
- Если есть дополнительные поля о клиенте, аккуратно используй 1–2 из них для персонализации.
- Тон дружелюбный, без канцелярита и не «впаривающий».
- Длина: 80–180 слов.
- Никакого Markdown, только обычный текст с абзацами через пустую строку.
- В конце — короткое подписание (например, «С уважением, команда {company_name}»). Если имя компании неизвестно — просто «С уважением».
- НЕ вставляй сам Subject в тело и не повторяй бриф дословно.
"""


class GPTPersonalizer:
    def __init__(self, api_key: str, model: str) -> None:
        # timeout=60s, retries cover transient network blips and OpenAI 5xx/429.
        self._client = AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=3)
        self._model = model

    async def generate_body(self, *, subject: str, brief: str, recipient: Recipient) -> str:
        extra_lines = "\n".join(f"- {k}: {v}" for k, v in recipient.extra.items()) or "(дополнительных полей нет)"
        user_prompt = (
            f"Subject: {subject}\n\n"
            f"Бриф:\n{brief}\n\n"
            f"Клиент:\n- name: {recipient.name}\n{extra_lines}\n"
        )
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
