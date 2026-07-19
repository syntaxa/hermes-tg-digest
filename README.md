# Hermes TG Digest

Ежедневный дайджест Telegram-каналов на базе Hermes Agent.

Гибридная схема: Telethon-сборщик (no_agent) → LLM-генератор (agent) → Telethon-публикатор (no_agent).

## Архитектура

```
collect.py ──→ Telethon ──→ ~/.hermes/digest/data/today.json
 (no_agent, 03:55 MSK)

LLM-суммаризация ──→ ~/.hermes/digest/output.md
 (Hermes cron, agent, 04:00 MSK)

digest-publish.py ──→ Telethon ──→ Telegram-канал
 (no_agent, 04:02 MSK)
```

## Быстрый старт

1. Получить `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org)
2. Создать `~/.hermes/digest/config.json`:

```json
{
  "api_id": 12345,
  "api_hash": "xxx",
  "phone": "+790****4567"
}
```

3. Запустить авторизацию:

```bash
python collectors/collect.py --auth
```

4. Получить ID канала:

```bash
python collectors/collect.py --get-chat-id https://t.me/+invite_link
```

5. Добавить канал в `~/.hermes/digest/channels.json`:

```json
[{"id": "@countwithsasha", "title": "Поляков считает: AI, код и кейсы"}]
```

## Команды

| Команда | Описание |
|---|---|
| `python collect.py` | Собрать посты за 24ч (тихий режим, для cron) |
| `python collect.py --auth` | Интерактивная авторизация Telethon |
| `python collect.py --get-chat-id <link>` | Получить числовой ID канала |
| `python collect.py --channels` | Показать список каналов |
| `python publish/digest-publish.py` | Опубликовать дайджест в канал |

## Формат дайджеста

Telegram HTML (parse_mode="html") с группировкой по каналам:
- Заголовок канала → **жирный текст**
- Заголовок поста → ссылка (`<a href="..."><b>текст</b></a>`)
- Саммари — обычный текст после ссылки
- Умеренные эмодзи (📅, 📡)
- Русский язык
- Превью ссылок отключено (`link_preview=False`)

## Управление каналами

Каналы добавляются/удаляются через чат с Hermes — редактируется `~/.hermes/digest/channels.json`.
Поддерживаются публичные (`@username`) и приватные (ID) каналы.

## Расписание (MSK)

| Время | Cronjob | Действие |
|---|---|---|
| 03:55 | `digest-collect` | Сбор постов за 24ч |
| 04:00 | `digest-generator` | LLM-суммаризация → output.md |
| 04:02 | `digest-publish` | Публикация в канал |
