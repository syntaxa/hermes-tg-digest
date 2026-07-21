#!/usr/bin/env python3
"""
Digest Watchdog — no_agent cron.
Runs 25 min after generation starts (04:25 UTC / 07:25 MSK).
If output.md wasn't written today → generation failed → notify channel.
Silent on success (output.md exists and fresh).
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone
from telethon import TelegramClient

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
OUTPUT_FILE = BASE / "output.md"
REPORT_FILE = BASE / "data" / "collect-report.json"

TODAY = datetime.now(timezone.utc).date()


async def main():
    client = TelegramClient(
        str(BASE / "session" / "user"), cfg["api_id"], cfg["api_hash"]
    )
    await client.start()
    entity = await client.get_entity("https://t.me/+KhrdCfl650llYzNi")

    # 1. Check if output.md exists and is from today
    if OUTPUT_FILE.exists():
        mtime = datetime.fromtimestamp(OUTPUT_FILE.stat().st_mtime, tz=timezone.utc).date()
        if mtime == TODAY:
            print("✓ output.md is fresh — generation succeeded")
            return  # silent exit, all good

    # 2. output.md missing or stale → something failed
    #    Gather diagnostics
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
        # check if collect ran at all today
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
