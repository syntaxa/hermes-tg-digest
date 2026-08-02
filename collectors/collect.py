#!/usr/bin/env python3
"""
Hermes TG Digest — Collector
Telethon-based message collector for Telegram channels.
Designed for no_agent cron usage: silent on success, errors to stderr.

Usage:
  python collect.py                    # collect last 24h posts (silent on success)
  python collect.py --auth             # interactive authentication
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, errors
from telethon.errors import SessionPasswordNeededError

# --- Configuration -----------------------------------------------------------
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
BASE_DIR = Path(os.path.expanduser(cfg.get("digest_dir", "~/.hermes/digest")))
CONFIG_FILE_PATH = BASE_DIR / "config.json"
CHANNELS_FILE = BASE_DIR / "channels.json"
SESSION_DIR = BASE_DIR / "session"
DATA_DIR = BASE_DIR / "data"
# Shared user session across digests (optional).
# Set user_session_dir to point to the shared session directory.
USER_SESSION_DIR = Path(os.path.expanduser(
    cfg.get("user_session_dir", str(SESSION_DIR))
))


def ensure_dirs():
    for d in [BASE_DIR, SESSION_DIR, DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_channels():
    if not CHANNELS_FILE.exists():
        return []
    with open(CHANNELS_FILE) as f:
        return json.load(f)


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────


async def main():
    ensure_dirs()
    args = sys.argv[1:]

    if not args:
        await collect_posts()
    elif args[0] == "--auth":
        await auth_mode()
    elif args[0] == "--channels":
        print(json.dumps(load_channels(), ensure_ascii=False, indent=2))
    else:
        print(
            "Usage: python collect.py [--auth|--channels]",
            file=sys.stderr,
        )
        sys.exit(1)


# ─────────────────────────────────────────────
# client helpers
# ─────────────────────────────────────────────



def _get_api_creds():
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    if not api_id or not api_hash:
        print("ERROR: api_id and api_hash required. Set DIGEST_API_ID/DIGEST_API_HASH or create config.json.", file=sys.stderr)
        sys.exit(1)
    return {"api_id": api_id, "api_hash": api_hash}


# ─────────────────────────────────────────────
# auth mode
# ─────────────────────────────────────────────


async def auth_mode():
    """Interactive authentication. Run once to create session file."""
    creds = _get_api_creds()
    client = TelegramClient(
        str(SESSION_DIR / "user"), creds["api_id"], creds["api_hash"]
    )

    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Already authorized as {me.first_name} (@{me.username})")
        return

    phone = cfg.get("phone")
    if not phone:
        phone = input("Phone (+790****4567): ")

    await client.send_code_request(phone)
    code = input("Code (with spaces if needed): ")

    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        pw = input("2FA password: ")
        await client.sign_in(password=pw)

    me = await client.get_me()
    print(f"✅ Authorized as {me.first_name} (@{me.username})")
    print(f"   Session saved to {SESSION_DIR / 'user.session'}")


# ─────────────────────────────────────────────
# collect posts
# ─────────────────────────────────────────────


async def collect_posts():
    """Main collection: fetch last 24h posts from all subscribed channels.
    Silent on success (empty stdout) — designed for no_agent cron."""
    creds = _get_api_creds()
    channels = load_channels()

    if not channels:
        sys.exit(0)

    client = TelegramClient(
        str(USER_SESSION_DIR / "user"), creds["api_id"], creds["api_hash"]
    )
    await client.start()
    if not await client.is_user_authorized():
        print("Not authorized. Run --auth first.", file=sys.stderr)
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_posts = []

    for ch in channels:
        channel_id = ch.get("id") if isinstance(ch, dict) else ch
        channel_title = ch.get("title", "") if isinstance(ch, dict) else ""

        try:
            entity = await client.get_entity(channel_id)
            posts = []
            async for msg in client.iter_messages(
                entity, offset_date=since, reverse=True
            ):
                text = msg.text or ""

                if not text.strip():
                    continue

                if getattr(entity, "username", None):
                    link = f"https://t.me/{entity.username}/{msg.id}"
                else:
                    cid = entity.id
                    if cid < 0:
                        cid = abs(cid) % 10**12
                    link = f"https://t.me/c/{cid}/{msg.id}"

                posts.append({
                    "id": msg.id,
                    "date": msg.date.isoformat(),
                    "channel_id": entity.id,
                    "channel_title": entity.title or channel_title,
                    # 65536: авторские дайджесты (Refat #ReDigest и т.п.) длиннее
                    # лимита сообщения 4096 — обрезка ломала их распознавание.
                    # 4096 было калькой с Telegram-лимита, но относится к стороне
                    # публикации (split_digest), а не сбора.
                    "text": text[:65536],
                    "link": link,
                    "has_media": bool(msg.media),
                })

            all_posts.extend(posts)
            print(f"  ✓ {entity.title}: {len(posts)} posts", file=sys.stderr)

        except errors.FloodWaitError as e:
            print(f"  ⏳ Flood wait {e.seconds}s — skipping {channel_id}", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ {channel_id}: {type(e).__name__}: {e}", file=sys.stderr)

    # save
    data_file = DATA_DIR / f"{today}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(all_posts)} posts to {data_file}", file=sys.stderr)

    # cleanup: keep only last 2 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    for f in DATA_DIR.glob("*.json"):
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if file_date < cutoff:
                f.unlink()
                print(f"  🗑️ Cleaned: {f.name}", file=sys.stderr)
        except ValueError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
