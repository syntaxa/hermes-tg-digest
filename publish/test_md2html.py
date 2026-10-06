#!/usr/bin/env python3
"""Self-test for markdown_to_html() — the publish-side Markdown→HTML safety net.

Run:  python3 publish/test_md2html.py
"""
import importlib.util
import re
import sys
from pathlib import Path

from telethon.extensions import html as th_html

_MOD = Path(__file__).with_name("digest-publish.py")
_spec = importlib.util.spec_from_file_location("digest_publish", _MOD)
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}\n  got:  {got!r}\n  want: {want!r}")


def leftovers(text: str) -> dict:
    """Сколько объектов Markdown осталось бы литеральным текстом."""
    italics = [m for m in re.findall(r"(?<!_)__([^_\n]+)__(?!_)", text)
               if not re.fullmatch(r"[A-Za-z0-9.]+", m)]  # __init__ — не курсив
    return {
        "](md_link)": len(re.findall(r"\]\((?:https?://|tg://)", text)),
        "**": len(re.findall(r"(?<!\*)\*\*(?!\*)", text)) // 2,
        "__": len(italics),
        "~~": text.count("~~") // 2,
    }


# --- 1. базовые преобразования ------------------------------------------
check("link", dp.markdown_to_html("[DevDay OpenAI](https://t.me/ai_newz/4790)")[0],
      '<a href="https://t.me/ai_newz/4790">DevDay OpenAI</a>')
check("bold", dp.markdown_to_html("**Нейродайджест**")[0], "<b>Нейродайджест</b>")
check("italic", dp.markdown_to_html("__SI Force__")[0], "<i>SI Force</i>")
check("strike", dp.markdown_to_html("~~old~~")[0], "<s>old</s>")
check("dunder stays", dp.markdown_to_html("вызовет __init__ метод")[0],
      "вызовет __init__ метод")
check("nested in link", dp.markdown_to_html("[**Заголовок**](https://x.io/a)")[0],
      '<a href="https://x.io/a"><b>Заголовок</b></a>')

# --- 2. code не конвертируется -------------------------------------------
check("code span", dp.markdown_to_html("см. `**x**` и `[a](b)`")[0],
      "см. <code>**x**</code> и <code>[a](b)</code>")
check("code block", dp.markdown_to_html("```\n**y** [z](https://q.io)\n```")[0],
      "<pre>\n**y** [z](https://q.io)\n</pre>")

# --- 3. idempotency: повторный прогон не меняет результат ------------------
for sample in (
    '<b>Привет</b>\n<a href="https://t.me/x/1"><b>Заг</b></a>',
    '<a href="https://t.me/ai_newz/4790">DevDay OpenAI</a>',
):
    once, _ = dp.markdown_to_html(sample)
    twice, n2 = dp.markdown_to_html(once)
    check(f"idempotent ({sample[:24]}...)", (twice, n2), (sample, 0))

# --- 4. href не портится правилами акцентов -------------------------------
url = "https://ex.com/a__b?q=1**2"
check("href untouched", dp.markdown_to_html(f"[text]({url})")[0],
      f'<a href="{url}">text</a>')

# --- 5. недопустимые схемы не превращаются в ссылки ------------------------
check("no scheme", dp.markdown_to_html("[см. план](дело)")[0], "[см. план](дело)")

# --- 6. реальные данные: опубликованные сообщения канала -------------------
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import json, os, asyncio
    from telethon import TelegramClient

    root = json.load(open(os.path.expanduser("/home/hermes/.hermes/digest/config.json")))

    async def fetch():
        client = TelegramClient(
            os.path.expanduser("/home/hermes/.hermes/digest/session/user.session"),
            root["api_id"], root["api_hash"])
        await client.connect()
        msgs = await client.get_messages(3972727071, limit=10)
        out = [(m.id, m.raw_text or "") for m in msgs if m.raw_text]
        await client.disconnect()
        return out

    msgs = asyncio.run(fetch())
    total_before = total_after = 0
    for mid, raw in msgs:
        converted, n = dp.markdown_to_html(raw)
        th_html.parse(converted)  # raises on invalid Telegram HTML
        before, after = leftovers(raw), leftovers(converted)
        total_before += sum(before.values())
        total_after += sum(after.values())
        again, n2 = dp.markdown_to_html(converted)
        if again != converted or n2:
            FAILURES.append(f"msg {mid}: not idempotent")
        if sum(after.values()):
            FAILURES.append(f"msg {mid}: leftovers after conversion {after}")
    print(f"real messages: {len(msgs)}, markdown leftovers "
          f"{total_before} → {total_after}")
except Exception as e:  # noqa: BLE001 — публичный самотест, сеть опциональна
    print(f"(real-data check skipped: {e})")

# --- 7. сплит: лимит, целостность <a>, сохранность ссылок -------------------
def _big_item(i: int) -> str:
    line = ('- <a href="https://t.me/ai_newz/{i}"><b>Новость {i}</b></a> — '
            "текст поста, чтобы секция была длинной. ")
    return line.format(i=i) * 4 + "\n"


digest = ("📅 Дайджест\n\n📡 <b>эйай ньюз</b>\n<i>📋 Дайджест от автора:</i>\n"
          + "".join(_big_item(i) for i in range(4790, 4830)))
chunks = dp.split_digest(digest)
want_links = digest.count('<a href="https://t.me/ai_newz')
got_links = sum(c.count('<a href="https://t.me/ai_newz') for c in chunks)
check("split: ссылки сохранены", got_links, want_links)
check("split: куски влезают", all(len(c) <= dp.MAX_MSG for c in chunks), True)
for i, c in enumerate(chunks, 1):
    check(f"split: chunk {i} — сбалансированные <a>",
          c.count("<a href"), c.count("</a>"))
    try:
        th_html.parse(c)
    except Exception as e:  # noqa: BLE001
        FAILURES.append(f"split chunk {i}: invalid HTML: {e}")

# одиночная секция без границ по каналам (не должна упасть MessageTooLong)
solo = ("📄 Длинный текст без заголовков каналов\n\n"
        + "".join(f"строка номер {j} — довольно длинный текст, чтобы набрать "
                  f"лимит сообщения. А ещё пара предложений для длины.\n"
                  for j in range(80)))
solo_chunks = dp.split_digest(solo)
check("solo: куски влезают", all(len(c) <= dp.MAX_MSG for c in solo_chunks), True)
check("solo: текст не потерян", "".join(solo_chunks), solo)
for i, c in enumerate(solo_chunks, 1):
    try:
        th_html.parse(c)
    except Exception as e:  # noqa: BLE001
        FAILURES.append(f"solo chunk {i}: invalid HTML: {e}")

# --- результат -------------------------------------------------------------
if FAILURES:
    print(f"\n{len(FAILURES)} FAILED:")
    print("\n".join(FAILURES))
    sys.exit(1)
print("OK: all checks passed")
