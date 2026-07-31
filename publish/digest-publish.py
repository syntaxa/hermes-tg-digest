#!/usr/bin/env python3
"""Publish digest to Telegram channel via Telethon (bot mode)."""
import asyncio, sys, re, os, json
from pathlib import Path
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.tl.types import PeerChannel

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
        "DIGEST_BOT_TOKEN": ("bot_token", str),
        "DIGEST_DIR": ("digest_dir", str),
        "DIGEST_TAG": ("digest-tag", str),
    }
    for env_key, (cfg_key, caster) in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            cfg[cfg_key] = caster(val) if caster is not str else val
    return cfg

cfg = load_config()

BASE = Path(os.path.expanduser(cfg.get("digest_dir", "~/.hermes/digest")))
TARGET_CHANNEL_ID = cfg.get("target_channel_id")
DIGEST_TAG = cfg.get("digest-tag", "")

OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"
BOT_SESSION = BASE / "session" / "bot"

MAX_MSG = 4000  # Telegram hard limit ~4096 chars; stay under


def hard_split_section(block: str, limit: int) -> list[str]:
    """Split a single channel section that exceeds MAX_MSG (e.g. авторский
    дайджест вставлен целиком). Breaks at post-title boundaries
    (\n<a href="), then at paragraph boundaries. Every piece is valid
    standalone HTML (all tags are closed within their paragraph)."""
    # 1. split at post-title boundaries
    segs = re.split(r"(\n<a href=\")", block)
    units = [segs[0]] if segs[0] else []
    i = 1
    while i < len(segs):
        units.append(segs[i] + (segs[i + 1] if i + 1 < len(segs) else ""))
        i += 2
    # 2. paragraph-split any unit that alone exceeds limit
    final_units = []
    for u in units:
        if len(u) <= limit:
            final_units.append(u)
            continue
        paras = re.split(r"(\n\n)", u)
        buf = paras[0] if paras[0] else ""
        i = 1
        while i < len(paras):
            piece = paras[i] + (paras[i + 1] if i + 1 < len(paras) else "")
            if len(buf) + len(piece) <= limit:
                buf += piece
            else:
                if buf:
                    final_units.append(buf)
                buf = piece
            i += 2
        if buf:
            final_units.append(buf)
    # 3. greedy pack units into pieces <= limit
    pieces = []
    buf = ""
    for u in final_units:
        if len(buf) + len(u) <= limit:
            buf += u
        else:
            if buf:
                pieces.append(buf)
            buf = u
    if buf:
        pieces.append(buf)
    return pieces


def split_digest(text: str) -> list[str]:
    """Split digest at channel headers (\n📡 <b>) to stay under MAX_MSG.
    Sections that alone exceed MAX_MSG are hard-split at post/paragraph
    boundaries (sub-pieces labelled 'ч. N/M (продолжение)')."""
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
        tag_part = f" · {DIGEST_TAG}" if DIGEST_TAG else ""
        suffix_tpl = "\n\n— ⋅ — ⋅ —\n<i>ч. {}/{}" + tag_part + "</i>"
        expanded = []
        for idx, chunk in enumerate(chunks):
            label = f"ч. {idx + 1}/{total}"
            suffix = suffix_tpl.format(idx + 1, total)
            if len(chunk) + len(suffix) <= MAX_MSG:
                expanded.append(chunk + suffix)
                continue
            # Oversized section (single channel section > MAX_MSG).
            # Hard-split the raw chunk; sub-pieces share the part label.
            cont_suffix = "\n\n— ⋅ — ⋅ —\n<i>" + label + " (продолжение)" + tag_part + "</i>"
            limit = MAX_MSG - len(cont_suffix)
            subs = hard_split_section(chunk, limit)
            for j, sub in enumerate(subs):
                expanded.append(sub + (suffix if j == 0 else cont_suffix))
        return expanded

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

    errs = [ch for ch in report["channels"] if ch.get("status") == "error"]
    if not errs:
        print("  ✓ No collection errors to report")
        return False

    total = len(report["channels"])
    ok_count = report["total_ok"]

    lines = [
        "⚠️ <b>Неполный сбор данных</b>\n",
        f"<b>Успешно:</b> {ok_count} из {total} каналов\n",
    ]

    for ch in errs:
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
    print(f"  ⚠️ Transparency: sent {len(errs)} errors to channel")
    return True


async def cleanup():
    """Remove processed data files, leave .digest-published marker."""
    OUTPUT_FILE.unlink(missing_ok=True)
    for f in (BASE / "data").glob("*.json"):
        if f.name == "collect-report.json":
            continue
        f.unlink()
        print(f"  Cleaned: data/{f.name}")
    # Marker for watchdog: publish succeeded
    (BASE / ".digest-published").write_text(datetime.now(timezone.utc).isoformat())


async def main():
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    bot_token = cfg.get("bot_token")

    if not bot_token:
        print("ERROR: bot_token required in config.json or DIGEST_BOT_TOKEN env.", file=sys.stderr)
        sys.exit(1)
    if not all([api_id, api_hash]):
        print("ERROR: api_id and api_hash required.", file=sys.stderr)
        sys.exit(1)
    if not TARGET_CHANNEL_ID:
        print("ERROR: target_channel_id required in config.json.", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(str(BOT_SESSION), api_id, api_hash)
    await client.start(bot_token=bot_token)

    entity = await client.get_entity(PeerChannel(TARGET_CHANNEL_ID))

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
