#!/usr/bin/env python3
"""Publish digest to Syntax channels digest via Telethon."""
import asyncio, sys
from pathlib import Path
from telethon import TelegramClient
import json

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
OUTPUT_FILE = BASE / "output.md"

async def main():
    if not OUTPUT_FILE.exists():
        print("No output.md found", file=sys.stderr)
        sys.exit(0)  # silent — nothing to publish

    text = OUTPUT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(0)

    client = TelegramClient(str(BASE / "session" / "user"), cfg["api_id"], cfg["api_hash"])
    await client.start()
    entity = await client.get_entity("https://t.me/+your_invite_hash")

    await client.send_message(entity, text, parse_mode="html", link_preview=False)
    print(f"Published to {entity.title}")

    # cleanup: remove used files so stale data never re-publishes
    OUTPUT_FILE.unlink(missing_ok=True)
    for f in (BASE / "data").glob("*.json"):
        f.unlink()
        print(f"  Cleaned: data/{f.name}")

asyncio.run(main())
