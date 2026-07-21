#!/usr/bin/env python3
"""Publish digest to Syntax channels digest via Telethon."""
import asyncio, sys, re
from pathlib import Path
from telethon import TelegramClient
import json

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"

MAX_MSG = 4000  # Telegram hard limit ~4096 chars; stay under


def split_digest(text: str) -> list[str]:
    """Split digest at channel headers (\n📡 <b>) to stay under MAX_MSG."""
    if len(text) <= MAX_MSG:
        return [text]

    # split on channel headers, keep the delimiter
    parts = re.split(r"(\n📡 <b>)", text)
    # recombine: each odd element is a header, even is content between
    chunks = []
    buf = parts[0] if parts[0] else ""  # preamble (title + date line)
    i = 1
    while i < len(parts):
        header = parts[i]  # "\n📡 <b>..."
        body = parts[i + 1] if i + 1 < len(parts) else ""
        candidate = header + body
        if len(buf) + len(candidate) <= MAX_MSG:
            buf += candidate
        else:
            if buf:
                chunks.append(buf)
            buf = candidate
        i += 2
    if buf:
        chunks.append(buf)

    # Append "ч. N/N" suffix to each chunk
    total = len(chunks)
    if total > 1:
        suffix = "\n\n— ⋅ — ⋅ —\n<i>ч. {}/{} · @syntaxachannel</i>"
        for idx in range(total):
            chunks[idx] += suffix.format(idx + 1, total)

    return chunks


async def send_digest(client, entity) -> bool:
    """Send the digest message (split if too long). Returns True if sent."""
    if not OUTPUT_FILE.exists():
        print("No output.md found", file=sys.stderr)
        return False

    text = OUTPUT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return False

    chunks = split_digest(text)
    for i, chunk in enumerate(chunks, 1):
        await client.send_message(entity, chunk, parse_mode="html", link_preview=False)
        print(f"  Part {i}/{len(chunks)} sent ({len(chunk)} chars)")

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
