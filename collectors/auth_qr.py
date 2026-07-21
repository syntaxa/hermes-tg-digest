#!/usr/bin/env python3
"""Full auth in background: QR → scan → 2FA password via stdin (process.submit)."""
import asyncio, json, sys, os
from pathlib import Path
from telethon import TelegramClient, errors
import qrcode

CONFIG_FILE = Path(os.getenv("DIGEST_CONFIG", "config.json"))

def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    env_map = {
        "DIGEST_API_ID": ("api_id", int),
        "DIGEST_API_HASH": ("api_hash", str),
        "DIGEST_PHONE": ("phone", str),
        "DIGEST_DIR": ("digest_dir", str),
    }
    for env_key, (cfg_key, caster) in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            cfg[cfg_key] = caster(val) if caster is not str else val
    return cfg

cfg = load_config()
BASE = Path(os.path.expanduser(cfg.get("digest_dir", "~/.hermes/digest")))
SESSION_DIR = BASE / "session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
QR_PATH = BASE / "auth_qr.png"


async def read_line():
    loop = asyncio.get_event_loop()
    return (await loop.run_in_executor(None, sys.stdin.readline)).strip()


async def main():
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    if not api_id or not api_hash:
        print("E: api_id and api_hash required.", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(str(SESSION_DIR / "user"), api_id, api_hash)
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
