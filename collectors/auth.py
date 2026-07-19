#!/usr/bin/env python3
"""Single-process auth: sends code, prints for user, waits on stdin, signs in immediately."""
import asyncio, json, sys
from pathlib import Path
from telethon import TelegramClient, errors

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
SESSION_DIR = BASE / "session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

async def main():
    client = TelegramClient(str(SESSION_DIR / "user"), cfg["api_id"], cfg["api_hash"])
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"OK: Already authorized as {me.first_name} (@{me.username})")
        return

    # Send code
    await client.send_code_request(cfg["phone"])
    print("K: Code sent to your Telegram. Enter code:", flush=True)

    # Wait for code on stdin — same process, same connection
    loop = asyncio.get_event_loop()
    code = (await loop.run_in_executor(None, sys.stdin.readline)).strip()

    if not code:
        print("E: No code", file=sys.stderr)
        sys.exit(1)

    try:
        await client.sign_in(cfg["phone"], code)
    except errors.SessionPasswordNeededError:
        print("K: 2FA password:", flush=True)
        pw = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
        await client.sign_in(password=pw)

    me = await client.get_me()
    print(f"OK: Authorized as {me.first_name} (@{me.username})")

asyncio.run(main())
