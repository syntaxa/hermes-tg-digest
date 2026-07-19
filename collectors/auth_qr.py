#!/usr/bin/env python3
"""Full auth in background: QR → scan → 2FA password via stdin (process.submit)."""
import asyncio, json, sys, os
from pathlib import Path
from telethon import TelegramClient, errors
import qrcode

BASE = Path.home() / ".hermes" / "digest"
cfg = json.loads((BASE / "config.json").read_text())
SESSION_DIR = BASE / "session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
QR_PATH = Path.home() / ".hermes" / "digest" / "auth_qr.png"

async def read_line():
    """Read one line from stdin (non-blocking, works with process.submit)."""
    loop = asyncio.get_event_loop()
    return (await loop.run_in_executor(None, sys.stdin.readline)).strip()

async def main():
    client = TelegramClient(str(SESSION_DIR / "user"), cfg["api_id"], cfg["api_hash"])
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"OK: Already authorized as {me.first_name} (@{me.username})")
        return

    print("K: QR gen...")

    while True:
        qr = await client.qr_login()
        img = qrcode.make(qr.url)
        img.save(str(QR_PATH))
        print(f"K: QR saved")
        try:
            await asyncio.wait_for(qr.wait(), timeout=60)
            print("K: QR scanned!")
            break
        except asyncio.TimeoutError:
            print("K: QR expired")
            continue
        except errors.SessionPasswordNeededError:
            print("K: QR scanned! 2FA required. Password:")
            pw = await read_line()
            if not pw:
                print("E: No password")
                sys.exit(1)
            await client.sign_in(password=pw)
            break

    me = await client.get_me()
    print(f"OK: Authorized as {me.first_name} (@{me.username})")

asyncio.run(main())
