#!/usr/bin/env python3
"""Hermes TG Digest — generator (OpenCode V2).

Drives the OpenCode V2 session API directly (like movie-box / ytv-extractor)
instead of relying on a tool-using agent loop:

    read newest data/<YYYY-MM-DD>.json
    -> prompts/digest-system.md + data + directive
    -> POST /api/session (agent "build")
    -> POST /api/session/{id}/prompt (delivery "queue")
    -> poll GET /api/session/{id}/message until idle
    -> DELETE /api/session/{id} (always)
    -> write BASE/output.md
    -> publish/digest-publish.sh (unless --dry-run)

Designed for no_agent cron usage: logs to stderr, `[SILENT]` on stdout when
there is nothing to do or after a successful publish.

Usage:
  python digest-generate.py            # generate + publish
  python digest-generate.py --dry-run  # generate only, print output.md path

Environment:
  DIGEST_NAME / DIGEST_CONFIG       config resolution (same as collectors)
  DIGEST_DIR                        overrides digest_dir from config
  OPENCODE_API_URL                  default http://127.0.0.1:49374
  OPENCODE_SERVER_USERNAME          default opencode
  OPENCODE_SERVER_PASSWORD          HTTP Basic password
  OPENCODE_MODEL_ID                 default big-pickle
  OPENCODE_PROVIDER_ID              default opencode
  OPENCODE_TIMEOUT_SECONDS          overall polling deadline, default 600
  DIGEST_DRY_RUN=1                  same as --dry-run
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date
from pathlib import Path

# --- Configuration -----------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = REPO_ROOT / "prompts" / "digest-system.md"
PUBLISH_SCRIPT = REPO_ROOT / "publish" / "digest-publish.sh"

DEFAULT_DIGEST_DIR = "~/.hermes/digest"
DEFAULT_API_URL = "http://127.0.0.1:49374"
DEFAULT_MODEL_ID = "big-pickle"
DEFAULT_PROVIDER_ID = "opencode"
DEFAULT_TIMEOUT_SECONDS = 600.0
REQUEST_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5

_DATE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OpenCodeError(RuntimeError):
    """V2 session API failed (network, HTTP, outcome, timeout, empty answer)."""


def log(message: str) -> None:
    """Operational logs go to stderr; never include config or post contents."""
    print(f"[generate] {message}", file=sys.stderr, flush=True)


# --- Config resolution (same semantics as collect.py / digest-publish.sh) ----
def resolve_config_path(env=None) -> Path:
    """DIGEST_NAME -> DIGEST_CONFIG -> ~/.hermes/digest/config.json."""
    env = os.environ if env is None else env

    name = (env.get("DIGEST_NAME") or "").strip()
    if name:
        return _expand_path(
            f"~/.hermes/digest/digests/{name}/config.json", env
        )

    explicit = (env.get("DIGEST_CONFIG") or "").strip()
    if explicit:
        return _expand_path(explicit, env)

    return _expand_path("~/.hermes/digest/config.json", env)


def load_config(path: Path) -> dict:
    """Load the JSON config; never log its contents (it holds bot_token)."""
    if not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read config {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def resolve_base(cfg: dict, env=None) -> Path:
    """BASE = DIGEST_DIR env > config.digest_dir > ~/.hermes/digest."""
    env = os.environ if env is None else env
    value = env.get("DIGEST_DIR") or cfg.get("digest_dir") or DEFAULT_DIGEST_DIR
    return _expand_path(str(value), env)


def _expand_path(value: str, env=None) -> Path:
    env = os.environ if env is None else env
    value = str(value)
    if value == "~" or value.startswith("~/"):
        home = env.get("HOME") or str(Path.home())
        value = home + value[1:]
    return Path(value)


# --- Data discovery ----------------------------------------------------------
def find_newest_data(data_dir: Path) -> Path | None:
    """Newest data/*.json, preferring YYYY-MM-DD names over other files.

    `collect-report.json` belongs to the collector's transparency report and
    must never be treated as a day of posts.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return None

    candidates = [
        p
        for p in data_dir.glob("*.json")
        if p.is_file() and p.name != "collect-report.json"
    ]
    if not candidates:
        return None

    def sort_key(path: Path):
        if _DATE_NAME_RE.match(path.stem):
            return (1, path.stem, 0.0)
        try:
            return (0, "", path.stat().st_mtime)
        except OSError:
            return (0, "", 0.0)

    return max(candidates, key=sort_key)


def load_posts(path: Path) -> list:
    """Read a data file; must be a JSON array of post objects."""
    try:
        posts = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read data file {path}: {exc}") from exc
    if not isinstance(posts, list):
        raise ValueError(f"data file {path} is not a JSON array")
    return posts


# --- Prompt ------------------------------------------------------------------
def build_prompt(system_prompt: str, posts: list, day: str) -> str:
    """System prompt + explicit override of its tool/publish steps + data."""
    posts_json = json.dumps(posts, ensure_ascii=False, indent=2)
    return (
        system_prompt.rstrip()
        + "\n\n---\n\n"
        + "## Script task (supersedes the process steps above)\n\n"
        + "The instructions above were written for a tool-using agent. Ignore "
        + "the file-reading, `write_file`, `terminal` and publish steps: you "
        + "have no tools. Do not read files, do not write files, do not run "
        + "commands and do not publish anything — the script does all of that "
        + "after receiving your answer.\n\n"
        + f"Today is {day}. The posts for the last 24 hours follow below as a "
        + "JSON array.\n\n"
        + "```json\n"
        + posts_json
        + "\n```\n\n"
        + "Reply with the finished digest in Telegram HTML and nothing else — "
        + "no preamble, no explanation, no code fences.\n"
    )


# --- Post-processing ---------------------------------------------------------
def strip_code_fences(text: str) -> str:
    """Strip one surrounding ``` fence (e.g. ```html ... ```), then whitespace."""
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    body = text[first_newline + 1:].rstrip()
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def looks_like_digest(text: str) -> bool:
    """Same sanity check publish uses: a link plus a date/feed marker."""
    return "<a href=" in text and ("📅" in text or "📡" in text)


# --- OpenCode V2 client (port of movie-box/src/opencode.ts) ------------------
def _opencode_config(env=None):
    env = os.environ if env is None else env
    api_url = (env.get("OPENCODE_API_URL") or DEFAULT_API_URL).rstrip("/")
    headers = {"Content-Type": "application/json"}
    password = env.get("OPENCODE_SERVER_PASSWORD")
    if password:
        username = env.get("OPENCODE_SERVER_USERNAME") or "opencode"
        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return api_url, headers


def _request(api_url: str, headers: dict, path: str, method: str = "GET",
             payload: dict | None = None, timeout: float = REQUEST_TIMEOUT_SECONDS):
    """One HTTP request; raise OpenCodeError on any non-2xx or network failure."""
    url = f"{api_url}{path}"
    data = None if payload is None else json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # Do not echo the body: a failed prompt response could contain the prompt.
        raise OpenCodeError(
            f"{method} {path} failed with HTTP {exc.code} {exc.reason}".rstrip()
        ) from exc
    except OSError as exc:
        raise OpenCodeError(f"{method} {path} connection failed: {exc}") from exc

    if not 200 <= status < 300:
        raise OpenCodeError(f"{method} {path} failed with HTTP {status}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise OpenCodeError(f"{method} {path} returned invalid JSON") from exc


def _extract_text(message: dict) -> str | None:
    parts = message.get("content") or []
    chunks = [
        part.get("text")
        for part in parts
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    text = "\n".join(chunks).strip()
    return text or None


def _find_final_assistant(messages: list) -> dict | None:
    """Newest completed assistant message, preferring a non-tool-call finish."""
    completed = [
        message
        for message in messages
        if isinstance(message, dict)
        and message.get("type") == "assistant"
        and isinstance(message.get("time"), dict)
        and message["time"].get("completed") is not None
    ]
    for message in completed:
        if message.get("finish") != "tool-calls":
            return message
    return completed[0] if completed else None


def _timeout_from_env(env) -> float:
    raw = env.get("OPENCODE_TIMEOUT_SECONDS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        log(f"invalid OPENCODE_TIMEOUT_SECONDS={raw!r}, using default")
        return DEFAULT_TIMEOUT_SECONDS
    return max(1.0, value)


def generate_text(prompt: str, *, title: str = "Hermes digest",
                  model_id: str | None = None,
                  provider_id: str | None = None,
                  timeout: float | None = None,
                  env=None) -> str:
    """Run one prompt through the V2 session API and return assistant text.

    Creates a session, queues the prompt, polls until `idle`, extracts the
    final completed assistant message, then always deletes the session.
    Raises OpenCodeError on any failure (including timeout / empty answer).
    """
    env = os.environ if env is None else env
    model_id = model_id or env.get("OPENCODE_MODEL_ID") or DEFAULT_MODEL_ID
    provider_id = provider_id or env.get("OPENCODE_PROVIDER_ID") or DEFAULT_PROVIDER_ID
    timeout = _timeout_from_env(env) if timeout is None else max(1.0, float(timeout))
    api_url, headers = _opencode_config(env)

    deadline = time.monotonic() + timeout
    session_id: str | None = None

    try:
        created = _request(
            api_url,
            headers,
            "/api/session",
            method="POST",
            payload={
                "title": title,
                "agent": "build",
                "model": {"id": model_id, "providerID": provider_id},
            },
        )
        data = created.get("data") if isinstance(created, dict) else None
        session_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise OpenCodeError("session creation response did not include an id")

        log(f"V2 session {session_id} created (model={model_id}/{provider_id})")

        _request(
            api_url,
            headers,
            f"/api/session/{urllib.parse.quote(session_id, safe='')}/prompt",
            method="POST",
            payload={"text": prompt, "delivery": "queue"},
        )

        while True:
            body = _request(
                api_url,
                headers,
                f"/api/session/{urllib.parse.quote(session_id, safe='')}/message",
                method="GET",
            )
            messages = body.get("data") if isinstance(body, dict) else None
            if not isinstance(messages, list):
                messages = []

            idle = next(
                (m for m in messages if isinstance(m, dict) and m.get("type") == "idle"),
                None,
            )
            if idle is not None:
                outcome = idle.get("outcome")
                if outcome != "succeeded":
                    raise OpenCodeError(f"session ended with outcome {outcome!r}")
                final = _find_final_assistant(messages)
                if final is None:
                    raise OpenCodeError(
                        "session succeeded but produced no completed assistant message"
                    )
                text = _extract_text(final)
                if not text:
                    raise OpenCodeError("session succeeded but the answer was empty")
                return text

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpenCodeError(
                    f"timed out after {timeout:.0f}s waiting for session idle"
                )
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    finally:
        if session_id:
            try:
                _request(
                    api_url,
                    headers,
                    f"/api/session/{urllib.parse.quote(session_id, safe='')}",
                    method="DELETE",
                )
                log(f"V2 session {session_id} deleted")
            except OpenCodeError as exc:
                log(f"warning: session cleanup failed: {exc}")


# --- Main --------------------------------------------------------------------
def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Generate and publish the Telegram digest via OpenCode V2."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate output.md but do not publish",
    )
    return parser.parse_args(argv)


def _publish(env: dict) -> int:
    """Run publish/digest-publish.sh and propagate its exit code."""
    publish_env = dict(env)
    name = env.get("DIGEST_NAME")
    if name:
        publish_env["DIGEST_NAME"] = name
    else:
        # Preserve the wrapper's existing fallback to DIGEST_CONFIG/default.
        publish_env.pop("DIGEST_NAME", None)

    log("publishing via publish/digest-publish.sh")
    result = subprocess.run(
        ["bash", str(PUBLISH_SCRIPT)],
        env=publish_env,
        check=False,
    )
    if result.returncode != 0:
        log(f"ERROR: publish exited with code {result.returncode}")
        return result.returncode

    print("[SILENT]")
    return 0


def main(argv=None, env=None) -> int:
    env = dict(os.environ if env is None else env)
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    dry_run = bool(args.dry_run or env.get("DIGEST_DRY_RUN") == "1")

    try:
        config_path = resolve_config_path(env)
        cfg = load_config(config_path)
        base = resolve_base(cfg, env)
    except ValueError as exc:
        log(f"ERROR: {exc}")
        return 1

    data_file = find_newest_data(base / "data")
    if data_file is None:
        print("[SILENT]")
        return 0

    try:
        posts = load_posts(data_file)
    except ValueError as exc:
        log(f"ERROR: {exc}")
        return 1

    if not posts:
        # Genuinely empty day (the collector ran and wrote an empty array).
        # Publish must still run: it sends the "no posts" notice AND writes
        # the .digest-published marker the 04:25 watchdog checks. Skipping it
        # would make the watchdog report a failed day.
        stale_output = base / "output.md"
        if stale_output.exists():
            # A previous failed run may have left a digest behind; publish
            # would otherwise adopt and re-send it as today's.
            try:
                stale_output.unlink()
            except OSError as exc:
                log(f"warning: cannot remove stale {stale_output}: {exc}")
        log(f"no posts today in {data_file}; letting publish send the empty-day notice")
        if dry_run:
            print("[SILENT]")
            return 0
        return _publish(env)

    day = data_file.stem if _DATE_NAME_RE.match(data_file.stem) else _date.today().isoformat()

    try:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        log(f"ERROR: cannot read system prompt {PROMPT_FILE}: {exc}")
        return 1

    prompt = build_prompt(system_prompt, posts, day)
    log(f"data: {data_file} ({len(posts)} post(s))")

    try:
        answer = generate_text(prompt, title=f"hermes-digest-{day}", env=env)
    except OpenCodeError as exc:
        log(f"ERROR: OpenCode V2 generation failed: {exc}")
        return 1
    except Exception as exc:  # unexpected bug / mock failure: fail loudly
        log(f"ERROR: generation failed: {type(exc).__name__}: {exc}")
        return 1

    text = strip_code_fences(answer)
    if not looks_like_digest(text):
        log(
            "ERROR: generated answer failed the sanity check "
            "(needs '<a href=' and '📅' or '📡'); refusing to publish"
        )
        return 1

    output_file = (base / "output.md").resolve()
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        log(f"ERROR: cannot write {output_file}: {exc}")
        return 1
    log(f"wrote {output_file} ({len(text)} chars)")

    if dry_run:
        print(str(output_file))
        return 0

    return _publish(env)


if __name__ == "__main__":
    sys.exit(main())
