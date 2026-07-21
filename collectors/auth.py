#!/usr/bin/env python3
"""Single-process auth: sends code, prints for user, waits on stdin, signs in immediately."""
import asyncio, json, sys, os
from pathlib import Path
from telethon import TelegramClient, errors

# Let DIGEST_CONFIG env var or DIGEST_DIR override working directory
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

async def main():
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    if not api_id or not api_hash:
        print("E: api_id and api_hash required. Set DIGEST_API_ID/DIGEST_API_HASH or create config.json.", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(str(SESSION_DIR / "user"), api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"OK: Already authorized as {me.first_name} (@{me.username})")
        return

    # Send code
    phone = cfg.get("phone")
    if not phone:
        print("E: phone number required. Set DIGEST_PHONE or add to config.json.", file=sys.stderr)
        sys.exit(1)

    await client.send_code_request(phone)
    print("K: Code sent to your Telegram. Enter code:", flush=True)

    loop = asyncio.get_event_loop()
    code = (await loop.run_in_executor(None, sys.stdin.readline)).strip()

    if not code:
        print("E: No code", file=sys.stderr)
        sys.exit(1)

    try:
        await client.sign_in(phone, code)
    except errors.SessionPasswordNeededError:
        print("K: 2FA password:", flush=True)
        pw = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
        await client.sign_in(password=pw)

    me = await client.get_me()
    print(f"OK: Authorized as {me.first_name} (@{me.username})")

asyncio.run(main())
