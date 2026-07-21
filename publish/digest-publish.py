#!/usr/bin/env python3
"""Publish digest to Telegram channel via Telethon."""
import asyncio, sys, re, os, json
from pathlib import Path
from telethon import TelegramClient

# --- Configuration -----------------------------------------------------------
# Priority: env var > config.json > default
CONFIG_FILE = Path(os.getenv("DIGEST_CONFIG", "config.json"))

def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    # env vars override file
    env_map = {
        "DIGEST_API_ID": ("api_id", int),
        "DIGEST_API_HASH": ("api_hash", str),
        "DIGEST_PHONE": ("phone", str),
        "DIGEST_CHANNEL_LINK": ("channel_link", str),
        "DIGEST_DIR": ("digest_dir", str),
        "DIGEST_BRAND": ("brand", str),
    }
    for env_key, (cfg_key, caster) in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            cfg[cfg_key] = caster(val) if caster is not str else val
    return cfg

cfg = load_config()

BASE = Path(os.path.expanduser(cfg.get("digest_dir", "~/.hermes/digest")))
CHANNEL_LINK = cfg.get("channel_link", "")
BRAND = cfg.get("brand", "")

OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"

MAX_MSG = 4000  # Telegram hard limit ~4096 chars; stay under


def split_digest(text: str) -> list[str]:
    """Split digest at channel headers (\\n📡 <b>) to stay under MAX_MSG."""
    if len(text) <= MAX_MSG:
        return [text]

    parts = re.split(r"(\n📡 <b>)", text)
    chunks = []
    buf = parts[0] if parts[0] else ""
    i = 1
    while i < len(parts):
        header = parts[i]
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

    total = len(chunks)
    if total > 1:
        suffix = "\n\n— ⋅ — ⋅ —\n<i>ч. {}/{}" + (f" · {BRAND}" if BRAND else "") + "</i>"
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
        REPORT_FILE.unlink(missing_ok=True)

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
        if f.name == "collect-report.json":
            continue
        f.unlink()
        print(f"  Cleaned: data/{f.name}")


async def main():
    if not all([cfg.get("api_id"), cfg.get("api_hash")]):
        print("ERROR: api_id and api_hash required. Set DIGEST_API_ID/DIGEST_API_HASH env vars or create config.json.", file=sys.stderr)
        sys.exit(1)
    if not CHANNEL_LINK:
        print("ERROR: DIGEST_CHANNEL_LINK is required.", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(
        str(BASE / "session" / "user"), cfg["api_id"], cfg["api_hash"]
    )
    await client.start()
    entity = await client.get_entity(CHANNEL_LINK)

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
