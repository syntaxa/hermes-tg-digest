#!/usr/bin/env python3
"""
Hermes TG Digest — Collector
Telethon-based message collector for Telegram channels.
Designed for no_agent cron usage: silent on success, errors to stderr.

Usage:
  python collect.py                    # collect last 24h posts (silent on success)
  python collect.py --auth             # interactive authentication
  python collect.py --get-chat-id <link>  # resolve invite/username to numeric ID
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, errors
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerChannel

# --- paths ---
BASE_DIR = Path.home() / ".hermes" / "digest"
CONFIG_FILE = BASE_DIR / "config.json"
CHANNELS_FILE = BASE_DIR / "channels.json"
SESSION_DIR = BASE_DIR / "session"
DATA_DIR = BASE_DIR / "data"


def ensure_dirs():
    for d in [BASE_DIR, SESSION_DIR, DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_config():
    if not CONFIG_FILE.exists():
        print(
            "Config not found. Create ~/.hermes/digest/config.json:",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {"api_id": 12345, "api_hash": "xxx", "phone": "+790****4567"},
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_channels():
    if not CHANNELS_FILE.exists():
        return []
    with open(CHANNELS_FILE) as f:
        return json.load(f)


def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


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
    elif args[0] == "--get-chat-id" and len(args) >= 2:
        await resolve_chat_id(args[1])
    elif args[0] == "--channels":
        print(json.dumps(load_channels(), ensure_ascii=False, indent=2))
    else:
        print(
            "Usage: python collect.py [--auth|--get-chat-id <link>|--channels]",
            file=sys.stderr,
        )
        sys.exit(1)


# ─────────────────────────────────────────────
# client helpers
# ─────────────────────────────────────────────


async def get_client():
    config = load_config()
    client = TelegramClient(
        str(SESSION_DIR / "user"),
        config["api_id"],
        config["api_hash"],
    )
    await client.start()
    return client, config


# ─────────────────────────────────────────────
# auth mode
# ─────────────────────────────────────────────


async def auth_mode():
    """Interactive authentication. Run once to create session file."""
    config = load_config()
    client = TelegramClient(
        str(SESSION_DIR / "user"), config["api_id"], config["api_hash"]
    )

    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Already authorized as {me.first_name} (@{me.username})")
        return

    phone = config.get("phone")
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
# resolve chat ID
# ─────────────────────────────────────────────


async def resolve_chat_id(link: str):
    """Resolve invite link or @username to numeric channel ID."""
    client, _ = await get_client()
    try:
        entity = await client.get_entity(link)
        print(f"Title:     {entity.title}")
        print(f"Chat ID:   {entity.id}")
        print(f"Username:  @{getattr(entity, 'username', 'N/A')}")
        print()
        print("# You can now add to channels.json:")
        print(json.dumps(
            [{"id": entity.id, "title": entity.title}],
            ensure_ascii=False, indent=2
        ))
    except errors.rpcerrorlist.InviteHashExpiredError:
        print("❌ Invite link expired or invalid.", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Cannot resolve: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


# ─────────────────────────────────────────────
# collect posts
# ─────────────────────────────────────────────


async def collect_posts():
    """Main collection: fetch last 24h posts from all subscribed channels.
    Silent on success (empty stdout) — designed for no_agent cron."""
    config = load_config()
    channels = load_channels()

    if not channels:
        # not an error, just nothing to do — stay silent
        sys.exit(0)

    client = TelegramClient(
        str(SESSION_DIR / "user"), config["api_id"], config["api_hash"]
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

                # skip posts with no text content
                if not text.strip():
                    continue

                # build permalink
                if getattr(entity, "username", None):
                    link = f"https://t.me/{entity.username}/{msg.id}"
                else:
                    # private channel: use https://t.me/c/STRIPPED_ID/msg_id
                    cid = entity.id
                    if cid < 0:
                        cid = abs(cid) % 10**12
                    link = f"https://t.me/c/{cid}/{msg.id}"

                # detect digest-like posts (repoasts of someone else's digest)
                t_lower = text.lower()
                is_digest = any(kw in t_lower for kw in [
                    "дайджест", "digest", "еженедельн",
                    "итоги недели", "итоги месяца",
                    "ежедневный дайджест", "подборка",
                    "дайджест ", " digest", "дайджест:",
                ])

                posts.append({
                    "id": msg.id,
                    "date": msg.date.isoformat(),
                    "channel_id": entity.id,
                    "channel_title": entity.title or channel_title,
                    "text": text[:4096],  # cap per-post
                    "link": link,
                    "has_media": bool(msg.media),
                    "is_digest": is_digest,
                })

            all_posts.extend(posts)
            # stderr for progress — invisible in no_agent delivery
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

    # stdout is empty → no_agent stays silent
    # stderr goes to Hermes logs


if __name__ == "__main__":
    asyncio.run(main())
