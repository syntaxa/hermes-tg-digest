# Hermes TG Digest

Ежедневный дайджест Telegram-каналов с LLM-суммаризацией.

Telethon-сборщик → LLM-генератор → публикация в Telegram-канал.
Работает как автономный пайплайн внутри [Hermes Agent](https://hermes-agent.nousresearch.com).

## Как это работает

```
┌──────────────────────┐
│ 1. Collect (06:55 MSK)│  Telethon → посты за 24ч → JSON
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 2. Generate + Publish│  LLM → HTML-дайджест → Telegram
│    (07:00 MSK)        │  (синхронно, в одной джобе)
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 3. Watchdog (07:25)  │  Если gen упал → диагностика в канал
└──────────────────────┘
```

- **Collect** — no_agent скрипт, тихий при успехе
- **Generate + Publish** — LLM-агент читает JSON, пишет дайджест (HTML), сразу отправляет в канал через Telethon
- **Watchdog** — no_agent, подстраховка: если output.md не обновлён → уведомление с диагностикой в канал

## Быстрый старт

### 1. Установка

```bash
git clone https://github.com/syntaxa/hermes-tg-digest.git
cd hermes-tg-digest
pip install -r requirements.txt
```

### 2. Конфигурация

Создайте `config.json` в рабочей директории (по умолчанию `~/.hermes/digest/`):

```json
{
  "api_id": 12345,
  "api_hash": "your_api_hash_from_my_telegram_org",
  "phone": "+79001234567",
  "channel_link": "https://t.me/+invite_link_or_@username",
  "digest_dir": "~/.hermes/digest",
  "brand": "@yourusername"
}
```

Или используйте переменные окружения (см. `.env.example`):

```bash
export DIGEST_API_ID=12345
export DIGEST_API_HASH=xxx
export DIGEST_PHONE=+79001234567
export DIGEST_CHANNEL_LINK=https://t.me/+...
```

### 3. Авторизация Telethon

**Рекомендуется QR-логин:**

```bash
python3 collectors/auth_qr.py
```

Или code-based:

```bash
python3 collectors/auth.py
```

### 4. Добавьте каналы

Создайте `channels.json` в рабочей директории:

```json
[
  {"id": "@channelusername", "title": "Channel Name"},
  {"id": -1001234567890, "title": "Private Channel"}
]
```

Получить числовой ID канала:

```bash
python3 collectors/collect.py --get-chat-id https://t.me/+invite_link
```

### 5. Запустите сбор и публикацию

```bash
python3 collectors/collect.py
python3 publish/digest-publish.sh
```

### 6. Настройка расписания (Hermes Agent)

В Hermes cron:

| Джоба | Время (MSK) | Тип | Команда |
|-------|-------------|-----|---------|
| Collect | 06:55 | no_agent | `digest-collect.sh` |
| Gen+Pub | 07:00 | agent | LLM-промпт + `publish/digest-publish.sh` |
| Watchdog | 07:25 | no_agent | `digest-watchdog.sh` |

## Команды

| Команда | Описание |
|---------|----------|
| `python3 collectors/collect.py` | Собрать посты за 24ч (тихий, для cron) |
| `python3 collectors/collect.py --auth` | Интерактивная авторизация |
| `python3 collectors/collect.py --get-chat-id <link>` | Получить ID канала |
| `python3 collectors/collect.py --channels` | Показать список каналов |
| `python3 collectors/auth_qr.py` | QR-логин (рекомендуется) |
| `python3 collectors/auth.py` | Code-based логин (fallback) |
| `bash publish/digest-publish.sh` | Опубликовать дайджест |
| `python3 publish/digest-watchdog.py` | Проверка, что gen сработал |

## Формат дайджеста

Telegram HTML через Telethon (`parse_mode="html"`, `link_preview=False`):

```
📅 Дайджест · 21 июля 2026

📡 <b>Channel Name</b>
<a href="https://t.me/channel/1234"><b>Заголовок поста</b></a>
Саммари ключевых идей — 2-4 предложения.
```

Дайджесты длиннее 4000 символов автоматически разбиваются по каналам.

## Структура репозитория

```
.
├── LICENSE                 ← MIT
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example            ← шаблон env-переменных
├── channels.example.json   ← шаблон списка каналов
├── collectors/
│   ├── auth.py             ← Code-based auth (fallback)
│   ├── auth_qr.py          ← QR-логин (preferred)
│   ├── collect.py          ← Telethon-скрипт сбора
│   └── config.example.json ← шаблон config.json
├── publish/
│   ├── digest-publish.py   ← Telethon-паблишер
│   ├── digest-publish.sh   ← wrapper для вызова
│   └── digest-watchdog.py  ← Watchdog ошибок генерации
└── prompts/
    └── digest-system.md    ← системный промпт для LLM
```

## Конфигурация

Все параметры читаются в порядке приоритета: **переменные окружения** → **config.json** → **умолчания**.

| Переменная | config.json ключ | Описание |
|-----------|-----------------|----------|
| `DIGEST_API_ID` | `api_id` | API ID с my.telegram.org (int) |
| `DIGEST_API_HASH` | `api_hash` | API Hash |
| `DIGEST_PHONE` | `phone` | Номер телефона |
| `DIGEST_CHANNEL_LINK` | `channel_link` | Ссылка на канал для публикации |
| `DIGEST_DIR` | `digest_dir` | Рабочая директория (default: `~/.hermes/digest`) |
| `DIGEST_BRAND` | `brand` | Суффикс в сплите (опционально) |

## Лицензия

MIT — делайте что хотите.
