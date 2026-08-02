# Hermes TG Digest — Agent Setup Guide

Когда пользователь говорит «настрой дайджест» или «разверни проект», используй
этот гайд для интерактивного onboarding'а.

## Мульти-дайджест

Система поддерживает несколько изолированных дайджестов в отдельных каналах.
Общая структура:

```
~/.hermes/digest/
├── config.json              ← api_id, api_hash, phone (общие)
├── session/user.session     ← одна user-сессия
└── digests/
    ├── syntax/config.json + channels.json + session/bot + data/
    └── tech/config.json + channels.json + session/bot + data/
```

Выбор дайджеста — через `DIGEST_NAME` (отражается на `~/.hermes/digest/digests/$DIGEST_NAME/config.json`).
Каждый дайджест = свой конфиг, бот, каналы, таргет-канал.

**Первичная настройка** (ниже) создаёт первый дайджест. Для добавления второго —
создай новую папку `digests/<name>/` с собственным `config.json`, `channels.json`,
и настрой отдельные cron-джобы с переопределённым `DIGEST_NAME`.

## Workflow: Первичная настройка

Выполняй шаги последовательно, задавая вопросы через `clarify()`.
Не делай ничего без явного ответа пользователя.

---

### 1. Проверка предустановок

Проверь, что есть Python ≥ 3.11, pip, git:

```bash
python3 --version && pip --version && git --version
```

Если чего-то нет — сообщи и остановись.

### 2. Клонирование (если ещё не)

```bash
cd ~
git clone https://github.com/syntaxa/hermes-tg-digest.git
cd hermes-tg-digest
```

Если репозиторий уже склонирован — перейди в него и проверь remote.

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Сбор конфигурации (через clarify)

Задай пользователю поочерёдно, через отдельные `clarify()`:

**4a. API ID и API Hash**

Зайди на [my.telegram.org](https://my.telegram.org) → API Development Tools → создать приложение.

```
Question: Введи API ID с my.telegram.org (целое число)
Choices: []
```

После ответа:
```
Question: Введи API Hash с my.telegram.org
Choices: []
```

**4b. Номер телефона**

```
Question: Номер телефона для Telegram (в формате +790****4567)
Choices: []
```

**4c. Бот для публикации**

Напиши [@BotFather](https://t.me/BotFather) → `/newbot` → получи токен.
Добавь бота в канал как **админа** с правом **публикации сообщений**.

```
Question: Введи bot_token от @BotFather
Choices: []
```

**4d. Канал для публикации**

```
Question: Ссылка на канал, куда публиковать дайджест (https://t.me/... или @username)
Choices: []
```

После получения ссылки — определи `target_channel_id`:

```bash
cd ~/hermes-tg-digest
python3 collectors/collect.py --get-chat-id <ссылка>
```

Если команда не сработала (бот не может резолвить инвайт) — попроси пользователя узнать ID через @userinfobot или @getidsbot в канале.

**4e. digest-tag (опционально)**

```
Question: Тег дайджеста для подписи в разбитых сообщениях (например "Tech Digest"). Оставь пустым если не нужно.
Choices: []
```

### 5. Создание config.json

Спроси у пользователя имя дайджеста (например `syntax`, `tech`, `news`).
Создай директорию и файл через `write_file`:

```bash
mkdir -p ~/.hermes/digest/digests/<name>/{session,data}
```

Создай `~/.hermes/digest/digests/<name>/config.json` через `write_file`:

```json
{
  "api_id": <api_id>,
  "api_hash": "<api_hash>",
  "phone": "<phone>",
  "bot_token": "<bot_token>",
  "target_channel_id": <target_channel_id>,
  "digest_dir": "~/.hermes/digest/digests/<name>",
  "user_session_dir": "~/.hermes/digest/session",
  "digest-tag": "<digest_tag>"
}
```

Поле `digest_dir` — куда collect.py и publish.py будут искать `data/`, `session/bot`, `output.md`.
Поле `user_session_dir` — общая папка с user.session (одна на все дайджесты).
Поле `digest-tag` — тег в подписи разбитых сообщений (бывш. `brand`).

### 6. Добавление каналов для мониторинга

```
Question: Ссылки на Telegram-каналы для сбора постов (через запятую).
Например: https://t.me/channel1, @channel2, https://t.me/+invitelink
Choices: []
```

После ответа распарсь список, для каждой ссылки выполни:

```bash
cd ~/hermes-tg-digest
python3 collectors/collect.py --get-chat-id <link>
```

Собери результат в `~/.hermes/digest/channels.json` через `write_file`:

```json
[
  {"id": "@channelusername", "title": "Название канала"},
  {"id": -1001234567890, "title": "Приватный канал"}
]
```

Поле `id` — строка (`@username`) или число (отрицательный ID канала).
Поле `title` — название для справки (LLM его не использует).

При ошибке `InviteHashExpiredError` — сообщи пользователю и попроси новую ссылку.

### 7. Авторизация Telethon

Предложи выбор через `clarify`:

```
Question: Способ авторизации?
Choices: ["QR-код (рекомендуется)", "Код по SMS"]
```

**QR-путь:**

```bash
cd ~/hermes-tg-digest
python3 collectors/auth_qr.py
```

Покажи QR-файл пользователю (через `image_generate` или `vision_analyze`).
Если потребуется 2FA — спроси пароль через `clarify`.

**Code-путь:**

Выполни auth.py в фоне с `pty=true`, передай код, который пользователь введёт.

Либо используй `collect.py --auth`:
```bash
cd ~/hermes-tg-digest
python3 collectors/collect.py --auth
```

### 8. Верификация

Проверь, что авторизация прошла:

```bash
cd ~/hermes-tg-digest
python3 collectors/collect.py --channels
```

Проверь публикацию от бота:

```bash
cd ~/hermes-tg-digest
DIGEST_CONFIG=~/.hermes/digest/digests/<name>/config.json python3 -c "
import asyncio, json, os
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import PeerChannel
cfg = json.load(open(os.path.expanduser('~/.hermes/digest/digests/<name>/config.json')))
BASE = Path(os.path.expanduser(cfg.get('digest_dir', '~/.hermes/digest/digests/<name>')))
async def test():
    client = TelegramClient(str(BASE / 'session' / 'bot'), cfg['api_id'], cfg['api_hash'])
    await client.start(bot_token=cfg['bot_token'])
    entity = await client.get_entity(PeerChannel(cfg['target_channel_id']))
    print(f'Channel: {entity.title}')
    await client.send_message(entity, '🔧 Тест — бот подключен', link_preview=False)
    print('✅ Test sent')
    await client.disconnect()
asyncio.run(test())
"
```

Проверь канал — тестовое сообщение должно появиться от имени бота.

### 9. Создание Hermes skill

Создай скилл `telegram-digest` для LLM-генератора:

```bash
cat ~/hermes-tg-digest/prompts/digest-system.md
```

Содержимое этого файла — системный промпт для LLM. Зарегистрируй его как Hermes skill через `skill_manage(action='create')` с именем `telegram-digest` и категорией `workflow`.

Этот скилл загружается в cron-джобе `digest-generator` и определяет:
- Как LLM группирует посты по каналам
- Формат HTML-дайджеста (теги, эмодзи, ссылки)
- Детекцию авторских дайджестов (confidence ≥ 7)
- Шаг публикации (вызов `bash publish/digest-publish.sh`)

### 10. Настройка shell-обёрток

В репозитории уже есть три обёртки, которые:
- Определяют `REPO_DIR` относительно своего расположения
- Экспортируют `DIGEST_CONFIG`: если задан `DIGEST_NAME` — резолвят в `~/.hermes/digest/digests/$DIGEST_NAME/config.json`, иначе — `~/.hermes/digest/config.json`
- Вызывают Python-скрипт с аргументами

| Обёртка | Вызывает | Тип cron |
|---------|----------|----------|
| `collectors/digest-collect.sh` | `collectors/collect.py` | no_agent |
| `publish/digest-publish.sh` | `publish/digest-publish.py` | вызывается LLM |
| `publish/digest-watchdog.sh` | `publish/digest-watchdog.py` | no_agent |

Сделай исполняемыми:

```bash
chmod +x ~/hermes-tg-digest/collectors/digest-collect.sh
chmod +x ~/hermes-tg-digest/publish/digest-publish.sh
chmod +x ~/hermes-tg-digest/publish/digest-watchdog.sh
```

### 11. Что дальше

Скажи пользователю:

> **Дайджест настроен.**
>
> - Сбор постов: `python3 collectors/collect.py`
> - Генерация + публикация: запускается Hermes cron (07:00 MSK)
> - Для ручного теста: `python3 collectors/collect.py && bash publish/digest-publish.sh`

Если Hermes cron ещё не настроен — спроси, нужно ли создать джобы (collector, generator, watchdog).

---

## Cron-джобы (Hermes Agent)

Если пользователь согласился настроить cron, создай через `cronjob`:

| Название | Расписание (UTC) | Тип | Скрипт | Скиллы |
|----------|-----------------|-----|--------|--------|
| digest-collector | `DIGEST_NAME=<name>` `55 3 * * *` | no_agent | `~/hermes-tg-digest/collectors/digest-collect.sh` | — |
| digest-generator | `DIGEST_NAME=<name>` `0 4 * * *` | agent | LLM промпт (см. «Создание cron-джобы») | `telegram-digest` |
| digest-watchdog | `DIGEST_NAME=<name>` `25 4 * * *` | no_agent | `~/hermes-tg-digest/publish/digest-watchdog.sh` | — |

**DIGEST_CONFIG** передаётся автоматически через обёртки (export в каждом .sh).
Не нужно дублировать env var в cron-джобах.

Уже существующие джобы не пересоздавай — проверь через `cronjob action='list'`.

---

## Если что-то пошло не так

- **FloodWaitError** — подожди и повтори через 10-15 минут
- **SessionPasswordNeededError** — запроси 2FA пароль
- **InviteHashExpiredError** — ссылка истекла, нужна новая
- **BotMethodInvalidError** — бот не может резолвить инвайт-ссылку, используй `target_channel_id`
- **ModuleNotFoundError** — проверь `pip install -r requirements.txt`
- **Не авторизован** — повтори шаг 7
- **Script not found** — проверь что .sh обёртки созданы и `chmod +x` (шаг 10)
