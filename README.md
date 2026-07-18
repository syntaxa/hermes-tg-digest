# Hermes TG Digest

Ежедневный дайджест Telegram-каналов на базе Hermes Agent.
Гибридная схема: Telethon-сборщик (no_agent) + LLM-генератор (agent).

## Архитектура

```
collect.py ──→ Telethon ──→ ~/.hermes/digest/data/today.json ──→ LLM-суммаризация ──→ Telegram-канал
 (no_agent, сбор за 24ч)                                          (Hermes cron, agent)
```

## Быстрый старт

1. Получить `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org)
2. Создать `~/.hermes/digest/config.json`
3. Запустить авторизацию: `python collectors/collect.py --auth`
4. Получить ID канала: `python collectors/collect.py --get-chat-id https://t.me/+invite_link`
5. Настроить cronjobs в Hermes
