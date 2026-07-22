#!/usr/bin/env python3
"""
Digest Watchdog — no_agent cron.
Runs 25 min after generation starts (04:25 UTC / 07:25 MSK).
If digest wasn't published → generation failed → notify channel.
Silent on success (marker file exists and is fresh).
"""
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone
from telethon import TelegramClient

# --- Configuration -----------------------------------------------------------
CONFIG_FILE = Path(os.getenv("DIGEST_CONFIG", "config.json"))

def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    env_map = {
        "DIGEST_API_ID": ("api_id", int),
        "DIGEST_API_HASH": ("api_hash", str),
        "DIGEST_CHANNEL_LINK": ("channel_link", str),
        "DIGEST_DIR": ("digest_dir", str),
    }
    for env_key, (cfg_key, caster) in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            cfg[cfg_key] = caster(val) if caster is not str else val
    return cfg

cfg = load_config()

BASE = Path(os.path.expanduser(cfg.get("digest_dir", "~/.hermes/digest")))
CHANNEL_LINK = cfg.get("channel_link", "")
OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"
MARKER_FILE = BASE / ".digest-published"

TODAY = datetime.now(timezone.utc).date()


def marker_ok():
    """Check if digest generation succeeded via .digest-published marker."""
    if not MARKER_FILE.exists():
        return False
    try:
        mtime = datetime.fromtimestamp(MARKER_FILE.stat().st_mtime, tz=timezone.utc).date()
        return mtime == TODAY
    except Exception:
        return False


async def main():
    if not all([cfg.get("api_id"), cfg.get("api_hash")]):
        print("ERROR: api_id and api_hash required.", file=sys.stderr)
        sys.exit(1)
    if not CHANNEL_LINK:
        print("ERROR: DIGEST_CHANNEL_LINK is required.", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(
        str(BASE / "session" / "user"), cfg["api_id"], cfg["api_hash"]
    )
    await client.start()
    entity = await client.get_entity(CHANNEL_LINK)

    # 1. Check if digest was published today via marker
    if marker_ok():
        print("✓ digest published today — watchdog silent")
        return  # silent exit, all good

    # 2. output.md missing or stale → something failed
    collect_ok = False
    errors = []
    if REPORT_FILE.exists():
        try:
            report = json.loads(REPORT_FILE.read_text())
            collect_ok = report.get("total_ok", 0) > 0
            err_channels = [c for c in report.get("channels", []) if c.get("status") == "error"]
            if err_channels:
                for c in err_channels:
                    errors.append(f"  • {c.get('title', '?')}: {c.get('error', '?')} — {c.get('detail', '')}")
        except Exception:
            pass

    lines = ["⚠️ <b>Дайджест не сформирован</b>\n"]

    if OUTPUT_FILE.exists() and datetime.fromtimestamp(OUTPUT_FILE.stat().st_mtime, tz=timezone.utc).date() < TODAY:
        lines.append("Дайджест остался со вчерашнего дня — генерация не обновила output.md.\n")
    else:
        lines.append("Генерация дайджеста не завершилась за отведённое время.\n")

    if collect_ok:
        lines.append("Сборщик отработал, но генератор не создал дайджест.\n")
        if errors:
            lines.append("Ошибки сбора (не влияют на генерацию, но для справки):")
            lines.extend(errors)
            lines.append("")
    else:
        collect_log = Path.home() / ".hermes" / "cron" / "output" / "digest-collector"
        if collect_log.exists():
            lines.append("Коллектор запускался, но не собрал данные (смотри collect-report.json).\n")
        else:
            lines.append("Коллектор не запускался сегодня.\n")

    text = "\n".join(lines)
    await client.send_message(entity, text, parse_mode="html", link_preview=False)
    print("⚠️ Watchdog: sent failure notification to channel")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
