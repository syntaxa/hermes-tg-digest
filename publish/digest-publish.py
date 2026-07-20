#!/usr/bin/env python3
"""Publish digest to Syntax channels digest via Telethon."""
import asyncio, sys
from pathlib import Path
from telethon import TelegramClient
import json

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"


async def send_digest(client, entity) -> bool:
    """Send the digest message. Returns True if sent."""
    if not OUTPUT_FILE.exists():
        print("No output.md found", file=sys.stderr)
        return False

    text = OUTPUT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return False

    await client.send_message(entity, text, parse_mode="html", link_preview=False)
    print("✅ Digest published")
    return True


async def send_transparency(client, entity) -> bool:
    """Send a transparency message about collection errors, if any.
    Returns True if a message was sent."""
    report = None
    if REPORT_FILE.exists():
        report = json.loads(REPORT_FILE.read_text())
        REPORT_FILE.unlink(missing_ok=True)  # consume once

    if not report:
        return False

    errors = [ch for ch in report["channels"] if ch.get("status") == "error"]
    if not errors:
        print("  ✓ No collection errors to report")
        return False

    total = len(report["channels"])
    ok_count = report["total_ok"]

    lines = [
        "⚠️ <b>Неполный сбор данных</b>\n",
        f"<b>Успешно:</b> {ok_count} из {total} каналов\n",
    ]

    for ch in errors:
        name = ch.get("title") or str(ch.get("id", "?"))
        err_type = ch.get("error", "UNKNOWN")
        detail = ch.get("detail", "")
        if err_type == "TIMEOUT":
            desc = f"⏱ Таймаут — {detail}"
        elif err_type == "FLOOD_WAIT":
            desc = f"🌊 FloodWait — {detail}"
        else:
            desc = f"❌ {err_type}: {detail}"
        lines.append(f"• <b>{name}</b> — {desc}")

    text = "\n".join(lines)
    await client.send_message(entity, text, parse_mode="html", link_preview=False)
    print(f"  ⚠️ Transparency: sent {len(errors)} errors to channel")
    return True


async def cleanup():
    """Remove processed data files."""
    OUTPUT_FILE.unlink(missing_ok=True)
    for f in (BASE / "data").glob("*.json"):
        # collect-report is already consumed and removed in send_transparency
        if f.name == "collect-report.json":
            continue
        f.unlink()
        print(f"  Cleaned: data/{f.name}")


async def main():
    client = TelegramClient(
        str(BASE / "session" / "user"), cfg["api_id"], cfg["api_hash"]
    )
    await client.start()
    entity = await client.get_entity("https://t.me/+your_invite_hash")

    # 1. Send the digest (if available)
    digest_sent = await send_digest(client, entity)

    # 2. Send transparency about collection errors (if any)
    transparency_sent = await send_transparency(client, entity)

    # 3. Fallback: if nothing was sent at all, inform channel
    if not digest_sent and not transparency_sent:
        msg = (
            "📭 <b>Нет новых постов за сегодня</b>\n\n"
            "Все каналы обработаны, но за последние 24 часа не найдено "
            "ни одного сообщения с текстом."
        )
        await client.send_message(entity, msg, parse_mode="html", link_preview=False)
        print("  📭 Sent no-content message")

    # 4. Cleanup
    await cleanup()

    print("✅ Publish complete")


asyncio.run(main())
