#!/usr/bin/env python3
"""Unit tests for generators/digest-generate.py.

No network and no publishing: `generate_text` and `subprocess.run` are mocked.
The OpenCode client itself (HTTP/polling) is exercised only in integration runs.

Run from the repo root:
  /home/hermes/venv/bin/python -m unittest generators.test_digest_generate -v
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_MOD = Path(__file__).with_name("digest-generate.py")
_spec = importlib.util.spec_from_file_location("digest_generate", _MOD)
dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dg)

DATE = "2026-10-23"
VALID_DIGEST = (
    "📅 Дайджест · 23 октября 2026\n\n"
    '📡 <b>Канал X</b>\n'
    '<a href="https://t.me/x/1"><b>Заголовок</b></a>\n'
    "Саммари в двух предложениях.\n"
)


class GeneratorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="digest-gen-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.base = self.root / "digest"
        (self.base / "data").mkdir(parents=True)
        self.config = self.base / "config.json"
        self.write_config(self.config, self.base)
        self.env = {"HOME": str(self.root), "DIGEST_CONFIG": str(self.config)}

    def write_config(self, path: Path, base: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"digest_dir": str(base)}, ensure_ascii=False),
            encoding="utf-8",
        )

    def write_data(self, day: str, posts: list) -> Path:
        path = self.base / "data" / f"{day}.json"
        path.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        return path

    def run_main(self, argv=("--dry-run",), env=None, answer=VALID_DIGEST):
        """Run main() with generate_text and publish mocked out."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(
            dg, "generate_text", return_value=answer
        ) as generate, mock.patch.object(dg, "subprocess") as subprocess_mock, \
                redirect_stdout(out), redirect_stderr(err):
            subprocess_mock.run.return_value = SimpleNamespace(returncode=0)
            code = dg.main(list(argv), dict(self.env if env is None else env))
        return code, out.getvalue(), err.getvalue(), generate, subprocess_mock

    # --- config resolution ---------------------------------------------------
    def test_config_resolution_digest_name_wins(self):
        env = {
            "HOME": str(self.root),
            "DIGEST_NAME": "demo",
            "DIGEST_CONFIG": "/tmp/other.json",
        }
        self.assertEqual(
            dg.resolve_config_path(env),
            self.root / ".hermes" / "digest" / "digests" / "demo" / "config.json",
        )

    def test_config_resolution_digest_config(self):
        env = {"HOME": str(self.root), "DIGEST_CONFIG": "~/custom.json"}
        self.assertEqual(dg.resolve_config_path(env), self.root / "custom.json")

    def test_config_resolution_default(self):
        env = {"HOME": str(self.root)}
        self.assertEqual(
            dg.resolve_config_path(env),
            self.root / ".hermes" / "digest" / "config.json",
        )

    def test_base_resolution_env_override(self):
        env = {"HOME": str(self.root), "DIGEST_DIR": "~/custom"}
        self.assertEqual(
            dg.resolve_base({"digest_dir": "/ignored"}, env),
            self.root / "custom",
        )

    def test_base_resolution_from_config(self):
        self.assertEqual(dg.resolve_base({"digest_dir": str(self.base)}, {}), self.base)

    # --- data discovery ------------------------------------------------------
    def test_newest_data_file_selected(self):
        self.write_data("2026-10-22", [{"text": "old"}])
        newest = self.write_data(DATE, [{"text": "new"}])
        (self.base / "data" / "collect-report.json").write_text(
            json.dumps({"channels": []}), encoding="utf-8"
        )
        self.assertEqual(dg.find_newest_data(self.base / "data"), newest)

    def test_newest_data_ignores_report_only(self):
        (self.base / "data" / "collect-report.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(dg.find_newest_data(self.base / "data"))

    # --- empty day / no data -------------------------------------------------
    def test_empty_posts_still_publishes_empty_day_notice(self):
        """Empty array = collector ran, nothing posted: publish must set the
        marker and send the "no posts" notice, or the watchdog false-alarms."""
        self.write_data(DATE, [])
        (self.base / "output.md").write_text("STALE DIGEST", encoding="utf-8")
        code, out, _err, generate, subprocess_mock = self.run_main(argv=())
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[SILENT]")
        self.assertFalse((self.base / "output.md").exists())  # stale removed
        generate.assert_not_called()
        subprocess_mock.run.assert_called_once()

    def test_empty_posts_dry_run_skips_publish(self):
        self.write_data(DATE, [])
        code, out, _err, generate, subprocess_mock = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[SILENT]")
        generate.assert_not_called()
        subprocess_mock.run.assert_not_called()

    def test_empty_posts_propagates_publish_failure(self):
        self.write_data(DATE, [])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(dg, "subprocess") as subprocess_mock, \
                redirect_stdout(out), redirect_stderr(err):
            subprocess_mock.run.return_value = SimpleNamespace(returncode=3)
            code = dg.main([], dict(self.env))
        self.assertEqual(code, 3)

    def test_no_data_file_prints_silent(self):
        code, out, _err, generate, subprocess_mock = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[SILENT]")
        self.assertFalse((self.base / "output.md").exists())
        generate.assert_not_called()
        subprocess_mock.run.assert_not_called()

    # --- prompt assembly -----------------------------------------------------
    def test_prompt_contains_system_prompt_data_and_date(self):
        self.write_data("2026-10-22", [{"text": "СТАРЫЙ ПОСТ"}])
        self.write_data(
            DATE,
            [{"text": "УНИКАЛЬНЫЙ ТЕКСТ ПОСТА", "channel_title": "Канал X"}],
        )
        code, out, _err, generate, _subprocess = self.run_main()
        self.assertEqual(code, 0)

        prompt = generate.call_args.args[0]
        self.assertIn("Daily Digest Generator — System Prompt", prompt)
        self.assertIn("УНИКАЛЬНЫЙ ТЕКСТ ПОСТА", prompt)
        self.assertNotIn("СТАРЫЙ ПОСТ", prompt)  # newest file wins
        self.assertIn("Канал X", prompt)
        self.assertIn(f"Today is {DATE}", prompt)
        self.assertIn(
            "Reply with the finished digest in Telegram HTML and nothing else", prompt
        )
        self.assertIn("no code fences", prompt)
        self.assertIn("write_file", prompt)  # told to ignore the tool steps
        self.assertEqual(Path(out.strip()), self.base / "output.md")

    # --- post-processing -----------------------------------------------------
    def test_strip_code_fences(self):
        self.assertEqual(
            dg.strip_code_fences("```html\n" + VALID_DIGEST + "\n```"),
            VALID_DIGEST.strip(),
        )
        self.assertEqual(dg.strip_code_fences("  plain text  "), "plain text")
        self.assertEqual(dg.strip_code_fences(VALID_DIGEST), VALID_DIGEST.strip())

    def test_sanity_check(self):
        self.assertTrue(dg.looks_like_digest(VALID_DIGEST))
        self.assertFalse(dg.looks_like_digest('<a href="x">link</a>'))
        self.assertFalse(dg.looks_like_digest("📅 date but no link"))
        self.assertFalse(dg.looks_like_digest(""))

    def test_sanity_failure_not_published(self):
        self.write_data(DATE, [{"text": "post"}])
        code, _out, err, _generate, subprocess_mock = self.run_main(
            argv=(), answer="просто текст без ссылок и эмодзи"
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.base / "output.md").exists())
        subprocess_mock.run.assert_not_called()
        self.assertIn("sanity check", err)

    def test_empty_answer_is_failure(self):
        self.write_data(DATE, [{"text": "post"}])
        code, _out, _err, _generate, subprocess_mock = self.run_main(
            argv=(), answer=""
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.base / "output.md").exists())
        subprocess_mock.run.assert_not_called()

    # --- dry run -------------------------------------------------------------
    def test_dry_run_writes_output_without_publish(self):
        self.write_data(DATE, [{"text": "post"}])
        code, out, _err, _generate, subprocess_mock = self.run_main(
            argv=("--dry-run",)
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(self.base / "output.md"))
        self.assertTrue((self.base / "output.md").is_absolute())
        self.assertTrue((self.base / "output.md").exists())
        subprocess_mock.run.assert_not_called()

    def test_dry_run_via_env(self):
        self.write_data(DATE, [{"text": "post"}])
        env = dict(self.env, DIGEST_DRY_RUN="1")
        code, out, _err, _generate, subprocess_mock = self.run_main(
            argv=(), env=env
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(self.base / "output.md"))
        subprocess_mock.run.assert_not_called()

    # --- publishing ----------------------------------------------------------
    def test_publish_success_prints_silent(self):
        self.write_data(DATE, [{"text": "post"}])
        code, out, _err, _generate, subprocess_mock = self.run_main(argv=())
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[SILENT]")
        self.assertTrue((self.base / "output.md").exists())
        subprocess_mock.run.assert_called_once()
        self.assertEqual(
            subprocess_mock.run.call_args.args[0],
            ["bash", str(dg.PUBLISH_SCRIPT)],
        )

    def test_publish_exit_code_propagates_and_keeps_output(self):
        named_base = self.root / "named"
        (named_base / "data").mkdir(parents=True)
        named_config = (
            self.root / ".hermes" / "digest" / "digests" / "demo" / "config.json"
        )
        self.write_config(named_config, named_base)
        (named_base / "data" / f"{DATE}.json").write_text(
            json.dumps([{"text": "post"}], ensure_ascii=False),
            encoding="utf-8",
        )

        env = {"HOME": str(self.root), "DIGEST_NAME": "demo"}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(
            dg, "generate_text", return_value=VALID_DIGEST
        ), mock.patch.object(dg, "subprocess") as subprocess_mock, \
                redirect_stdout(out), redirect_stderr(err):
            subprocess_mock.run.return_value = SimpleNamespace(returncode=3)
            code = dg.main([], env)

        self.assertEqual(code, 3)  # publish exit 3 propagates unchanged
        self.assertTrue((named_base / "output.md").exists())  # no cleanup here
        kwargs = subprocess_mock.run.call_args.kwargs
        self.assertEqual(kwargs["env"]["DIGEST_NAME"], "demo")

    def test_publish_env_omits_digest_name_when_unset(self):
        self.write_data(DATE, [{"text": "post"}])
        code, _out, _err, _generate, subprocess_mock = self.run_main(argv=())
        self.assertEqual(code, 0)
        publish_env = subprocess_mock.run.call_args.kwargs["env"]
        self.assertNotIn("DIGEST_NAME", publish_env)


if __name__ == "__main__":
    unittest.main()
