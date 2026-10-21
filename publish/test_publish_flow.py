#!/usr/bin/env python3
"""Self-test for the publish decision flow: stray output.md adoption +
the «Нет постов» guard (see digest-troubleshooting, Mode 8).

Covers the 2026-10-21 incident: the generator wrote output.md to ~/output.md,
publish found nothing, sent «📭 Нет новых постов за сегодня» and cleaned up
the collected data. Now publish must (a) adopt a fresh digest-shaped stray
file, and (b) refuse to send anything and keep the data when posts exist but
output.md does not.

Run:  python3 publish/test_publish_flow.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_MOD = Path(__file__).with_name("digest-publish.py")
_spec = importlib.util.spec_from_file_location("digest_publish", _MOD)
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)

FAILURES = []

DIGEST_SAMPLE = (
    "📅 Дайджест · 21 октября 2026\n\n"
    '📡 <b>Канал</b>\n<a href="https://t.me/x/1"><b>Заголовок</b></a>\nСаммари.\n'
)


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}\n  got:  {got!r}\n  want: {want!r}")


class tmpenv:
    """Подменяет BASE/OUTPUT_FILE на временный каталог на время теста."""

    def __init__(self):
        self._saved = None

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory(prefix="digest-flow-")
        base = Path(self.dir.name)
        self._saved = (dp.BASE, dp.OUTPUT_FILE)
        dp.BASE = base
        dp.OUTPUT_FILE = base / "output.md"
        (base / "data").mkdir()
        self.stray = base / "home" / "output.md"
        self.stray.parent.mkdir()
        return self

    def __exit__(self, *exc):
        dp.BASE, dp.OUTPUT_FILE = self._saved
        self.dir.cleanup()
        return False

    def write_stray(self, text=DIGEST_SAMPLE, age=0):
        self.stray.write_text(text, encoding="utf-8")
        os.utime(self.stray, (time.time() - age, time.time() - age))
        return self.stray


# --- 1. канонический файл главнее -----------------------------------------
with tmpenv() as t:
    dp.OUTPUT_FILE.write_text(DIGEST_SAMPLE, encoding="utf-8")
    t.write_stray()
    check("canonical wins", dp.resolve_output(candidates=[t.stray]), dp.OUTPUT_FILE)
    check("canonical keeps stray", t.stray.exists(), True)

# --- 2. свежий чужой output.md подбирается в BASE --------------------------
with tmpenv() as t:
    t.write_stray()
    got = dp.resolve_output(candidates=[t.stray])
    check("stray adopted path", got, dp.OUTPUT_FILE)
    check("stray adopted content", dp.OUTPUT_FILE.read_text(encoding="utf-8"),
          DIGEST_SAMPLE)
    check("stray removed from home", t.stray.exists(), False)

# --- 3. протухший файл не трогаем ------------------------------------------
with tmpenv() as t:
    t.write_stray(age=dp.STRAY_MAX_AGE + 60)
    check("stale ignored", dp.resolve_output(candidates=[t.stray]), None)
    check("stale kept", t.stray.exists(), True)

# --- 4. посторонний output.md (не дайджест) не трогаем ----------------------
with tmpenv() as t:
    t.write_stray(text="some other task output\nno links here\n")
    check("foreign ignored", dp.resolve_output(candidates=[t.stray]), None)

# --- 5. пустой канонический файл не считается дайджестом -------------------
with tmpenv() as t:
    dp.OUTPUT_FILE.write_text("", encoding="utf-8")
    t.write_stray()
    check("empty canonical replaced", dp.resolve_output(candidates=[t.stray]),
          dp.OUTPUT_FILE)
    check("empty canonical content", dp.OUTPUT_FILE.read_text(encoding="utf-8"),
          DIGEST_SAMPLE)

# --- 6. отсутствие кандидатов ----------------------------------------------
with tmpenv() as t:
    check("nothing to adopt", dp.resolve_output(candidates=[t.stray]), None)

# --- 7. решение: что делать, когда в канал ничего не ушло -------------------
check("digest published → cleanup", dp.decide(True, False, 7), "digest")
check("digest + transparency → cleanup", dp.decide(True, True, 7), "digest")
check("posts exist, no output → error", dp.decide(False, False, 7), "error")
check("posts exist, transparency only → error", dp.decide(False, True, 7), "error")
check("empty day → «no posts»", dp.decide(False, False, 0), "empty")
check("no posts + transparency → transparency", dp.decide(False, True, 0),
      "transparency")

# --- 8. collected_posts_count: только реальные посты ------------------------
with tmpenv() as t:
    data = dp.BASE / "data"
    (data / "2026-10-21.json").write_text(
        json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
    (data / "2026-10-20.json").write_text("[]", encoding="utf-8")
    (data / "collect-report.json").write_text(
        json.dumps({"channels": [], "total_ok": 5}), encoding="utf-8")
    (data / "broken.json").write_text("{not json", encoding="utf-8")
    check("posts counted, report skipped, broken skipped",
          dp.collected_posts_count(), 2)

# --- 9. инвариант инцидента: пустой день всё ещё получает «Нет постов」 -----
#    (collect.py пишет data/<today>.json = [] — файл есть, постов нет)
with tmpenv() as t:
    (dp.BASE / "data" / "2026-10-21.json").write_text("[]", encoding="utf-8")
    check("empty day file still → empty", dp.decide(False, False,
          dp.collected_posts_count()), "empty")


# --- 10-12. main() целиком, без сети (фейковый клиент) ----------------------
class FakeClient:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    async def start(self, **k):
        return self

    async def get_entity(self, peer):
        return "entity"

    async def send_message(self, entity, text, **k):
        FakeClient.sent.append(text)

    async def disconnect(self):
        pass


def run_main(stray: Path | None):
    """main() с подменённым TelegramClient; возвращает список отправленных."""
    import asyncio
    saved = (dp.TelegramClient, dp.cfg, dp.TARGET_CHANNEL_ID, dp.BASE,
             dp.OUTPUT_FILE, dp.REPORT_FILE, dp.BOT_SESSION,
             dp.default_candidates)
    dp.TelegramClient = FakeClient
    dp.cfg = {"api_id": 1, "api_hash": "x", "bot_token": "t"}
    dp.TARGET_CHANNEL_ID = -100123456
    dp.REPORT_FILE = dp.BASE / "data" / "collect-report.json"
    dp.default_candidates = lambda: ([stray] if stray else [])
    FakeClient.sent = []
    code = None
    try:
        asyncio.run(dp.main())
    except SystemExit as e:
        code = e.code
    finally:
        (dp.TelegramClient, dp.cfg, dp.TARGET_CHANNEL_ID, dp.BASE,
         dp.OUTPUT_FILE, dp.REPORT_FILE, dp.BOT_SESSION,
         dp.default_candidates) = saved
    return code, list(FakeClient.sent)


# 10. Реплей инцидента 21.10: посты собраны, output.md лежит в ~/ → publish
#     сам подбирает файл, шлёт дайджест ОДНИМ запуском, чистит, ставит маркер
with tmpenv() as t:
    posts_file = dp.BASE / "data" / "2026-10-21.json"
    posts_file.write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
    t.write_stray()
    code, sent = run_main(t.stray)
    check("incident: exit code", code, None)
    check("incident: one message", len(sent), 1)
    check("incident: it is the digest", sent[0].startswith("📅"), True)
    check("incident: no «Нет постов»", any("Нет новых постов" in m for m in sent),
          False)
    check("incident: data cleaned", posts_file.exists(), False)
    check("incident: marker set", (dp.BASE / ".digest-published").exists(), True)
    check("incident: stray consumed", t.stray.exists(), False)

# 11. Настоящая ошибка: посты есть, output.md нигде нет → выход 3,
#     в канал ничего не ушло, данные и маркер не тронуты
with tmpenv() as t:
    posts_file = dp.BASE / "data" / "2026-10-21.json"
    posts_file.write_text(json.dumps([{"id": 1}]), encoding="utf-8")
    code, sent = run_main(None)
    check("guard: exit 3", code, 3)
    check("guard: nothing sent", sent, [])
    check("guard: data kept", posts_file.exists(), True)
    check("guard: marker absent", (dp.BASE / ".digest-published").exists(), False)

# 12. Пустой день: постов нет, output.md нет → «Нет новых постов» + cleanup
with tmpenv() as t:
    posts_file = dp.BASE / "data" / "2026-10-21.json"
    posts_file.write_text("[]", encoding="utf-8")
    code, sent = run_main(None)
    check("empty day: exit code", code, None)
    check("empty day: notice sent",
          any("Нет новых постов" in m for m in sent), True)
    check("empty day: data cleaned", posts_file.exists(), False)
    check("empty day: marker set", (dp.BASE / ".digest-published").exists(), True)

# --- результат --------------------------------------------------------------
if FAILURES:
    print(f"FAIL: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("OK: all checks passed")