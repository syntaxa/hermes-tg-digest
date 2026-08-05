# Hermes TG Digest

Ежедневный дайджест Telegram-каналов с LLM-суммаризацией.

Telethon-сборщик → LLM-генератор → публикация в Telegram-канал от имени бота.
Работает как автономный пайплайн внутри [Hermes Agent](https://hermes-agent.nousresearch.com).

## Установка

Скажите Hermes:

```
Склонируй https://github.com/syntaxa/hermes-tg-digest.git в ~, установи зависимости, и настрой дайджест.
```

Hermes клонирует репозиторий, поставит зависимости и запустит onboarding — задаст вопросы по API, боту и каналам.

## Что это даёт

Каждое утро в вашем Telegram-канале появляется дайджест: саммари постов из выбранных каналов за сутки. Авторские дайджесты вставляются целиком.

**Почему от бота, а не от себя?** Если публиковать через свою пользовательскую сессию, Telegram помечает новые сообщения в канале как прочитанные — вы не увидите уведомлений. Бот публикует от своего имени, поэтому сообщения приходят как непрочитанные.

## Как это работает

```
06:55 MSK  Collect   → Telethon собирает посты за 24ч из каналов дайджеста → JSON
07:00 MSK  Gen+Pub   → LLM читает JSON → HTML-дайджест → публикация в канал
07:25 MSK  Watchdog  → Если генерация упала → диагностика в канал
```

### Мульти-дайджест

Поддерживается **несколько изолированных дайджестов** — каждый со своим каналом-получателем, ботом и набором каналов-источников. User-сессия одна общая.

```
~/.hermes/digest/
├── config.json              ← api_id, api_hash, phone (общие)
├── session/user.session     ← одна user-сессия на все дайджесты
└── digests/
    ├── syntax/config.json + channels.json + session/bot + data/
    └── tech/config.json + channels.json + session/bot + data/
```

Выбор дайджеста через `DIGEST_NAME=syntax` — обёртки резолвят конфиг в `~/.hermes/digest/digests/$DIGEST_NAME/config.json`.

## Быстрый старт

### 1. Клонируйте и установите зависимости

```bash
git clone https://github.com/syntaxa/hermes-tg-digest.git
cd hermes-tg-digest
pip install -r requirements.txt
```

### 2. Получите Telegram API

Зайдите на [my.telegram.org](https://my.telegram.org) → API Development Tools → создайте приложение.
Вам понадобятся `api_id` (число) и `api_hash` (строка).

### 3. Создайте бота

Напишите [@BotFather](https://t.me/BotFather), выполните `/newbot`, получите `bot_token`.
Добавьте бота в канал, куда будет публиковаться дайджест, как **админа** с правом **публикации сообщений**.

### 4. Настройте через Hermes

Попросите Hermes настроить дайджест — он сам создаст конфиг, авторизуется и добавит каналы:

```
Настрой дайджест.
Вот мои данные:
- api_id: 12345
- api_hash: ваш_api_hash
- phone: +790****5678
- bot_token: 1234567890:ABCdef...
- канал для публикации: https://t.me/ваш_канал
- каналы для сбора: https://t.me/channel1, @channel2, https://t.me/+invite
```

Hermes сам:
- Создаст `~/.hermes/digest/config.json`
- Разрешит ID каналов из ссылок
- Авторизуется через QR или SMS
- Настроит cron-расписание

### 5. Протестируйте

```bash
# Собрать посты
python3 collectors/collect.py

# Сформировать дайджест (через Hermes или вручную)
# Hermes: "сгенерируй дайджест"
# Вручную: скрипт collect.py → output.md → publish

# Опубликовать
python3 publish/digest-publish.sh
```

Проверьте канал — дайджест должен появиться от имени бота.

### 6. Cron-расписание

Hermes настроит три джобы автоматически при запросе «настрой дайджест».

Если настраиваете вручную:

| Джоба | Время (MSK) | Тип | Скрипт |
|-------|-------------|-----|--------|
| Collect | 06:55 | no_agent | `digest-collect.sh` |
| Gen+Pub | 07:00 | LLM | Промпт + `digest-publish.sh` |
| Watchdog | 07:25 | no_agent | `digest-watchdog.sh` |

## Управление каналами

Каналы добавляются и удаляются через Hermes (или редактируя `channels.json` соответствующего дайджеста):

```
добавить @username в дайджест syntax
добавить https://t.me/+invite_link
удалить @username
каналы
```

Каждый дайджест хранит свой список в `~/.hermes/digest/digests/<name>/channels.json`.

## Команды

| Команда | Описание |
|---------|----------|
| `DIGEST_NAME=<name> python3 collectors/collect.py` | Собрать посты за 24ч для дайджеста `<name>` |
| `DIGEST_NAME=<name> python3 collectors/collect.py --channels` | Показать список каналов дайджеста |
| `python3 collectors/auth_qr.py` | QR-логин (одна user-сессия на все дайджесты) |
| `python3 collectors/auth.py` | Code-based логин |
| `DIGEST_NAME=<name> bash publish/digest-publish.sh` | Опубликовать дайджест `<name>` |
| `DIGEST_NAME=<name> python3 publish/digest-watchdog.py` | Проверить, что генерация отработала |

## Конфигурация

`~/.hermes/digest/digests/<name>/config.json`:

```json
{
  "api_id": 12345,
  "api_hash": "ваш_api_hash",
  "phone": "+790****5678",
  "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
  "target_channel_id": -1001234567890,
  "digest_dir": "~/.hermes/digest/digests/<name>",
  "user_session_dir": "~/.hermes/digest/session",
  "digest-tag": "Мой Дайджест"
}
```

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `api_id` | ✅ | С my.telegram.org |
| `api_hash` | ✅ | С my.telegram.org |
| `phone` | ✅ | Номер телефона (для user-сессии сборщика) |
| `bot_token` | ✅ | Токен от @BotFather (для публикации) |
| `target_channel_id` | ✅ | Числовой ID канала публикации (отрицательное число) |
| `digest_dir` | ❌ | Рабочая директория дайджеста (по умолчанию `~/.hermes/digest/digests/<name>`) |
| `user_session_dir` | ❌ | Общая папка user.session для всех дайджестов (по умолчанию `~/.hermes/digest/session`) |
| `digest-tag` | ❌ | Тег в футере при разбиении дайджеста на части (заменяет `brand`) |

Общий конфиг `~/.hermes/digest/config.json` содержит только `api_id, api_hash, phone`.

## Формат дайджеста

Telegram HTML (`parse_mode="html"`, `link_preview=False`):

```
📅 Дайджест · 21 июля 2026

📡 <b>Channel Name</b>
<a href="https://t.me/channel/1234"><b>Заголовок поста</b></a>
Саммари ключевых идей — 2-4 предложения.

📋 Дайджест от автора:
(оригинальный текст дайджеста целиком)
```

Авторские дайджесты (LLM-тест: 3+ независимых тем в одном посте) вставляются целиком.
Дайджесты длиннее 4000 символов автоматически разбиваются по каналам.

## Структура репозитория

```
hermes-tg-digest/
├── README.md
├── requirements.txt
├── .env.example              ← шаблон переменных окружения
├── collectors/
│   ├── auth.py               ← Code-based auth
│   ├── auth_qr.py            ← QR-логин (рекомендуется)
│   └── collect.py            ← Сбор постов
├── publish/
│   ├── digest-publish.py     ← Публикация (от бота)
│   ├── digest-publish.sh     ← Wrapper для публикации
│   └── digest-watchdog.py    ← Watchdog ошибок генерации
└── prompts/
    └── digest-system.md      ← Системный промпт для LLM
```

Runtime (вне репозитория):

Первичная структура (старый single-digest путь) — больше не создаётся, оставлена для обратной совместимости:
```
~/.hermes/digest/
├── config.json              ← общий (api_id, api_hash, phone)
├── session/user.session     ← одна сессия на все дайджесты
└── digests/
    └── <name>/
        ├── config.json              ← креды + digest-tag + таргет
        ├── channels.json            ← каналы-источники
        ├── session/bot.session      ← сессия бота
        ├── data/YYYY-MM-DD.json     ← посты за день
        ├── output.md                ← сгенерированный дайджест
        └── .digest-published        ← маркер успешной публикации
```

## Безопасность

- `config.json` содержит `api_hash` и `bot_token` — **не коммитьте** в git
- `.gitignore` уже настроен, но проверьте перед first push
- Если репозиторий стал публичным — ротируйте credentials через my.telegram.org

## Лицензия

MIT — делайте что хотите.
