#!/bin/bash
# Wrapper for digest-watchdog.py — called by digest-watchdog no_agent cron
# Exports DIGEST_CONFIG so the watchdog finds config.json

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DIGEST_CONFIG="${DIGEST_CONFIG:-$HOME/.hermes/digest/config.json}"

exec python3 "$REPO_DIR/publish/digest-watchdog.py" "$@"
