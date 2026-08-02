#!/bin/bash
# Wrapper for digest-watchdog.py — called by digest-watchdog no_agent cron
# If DIGEST_NAME is set, resolves config from ~/.hermes/digest/digests/$DIGEST_NAME/
# Otherwise falls back to DIGEST_CONFIG env or ~/.hermes/digest/config.json

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -n "$DIGEST_NAME" ]; then
    export DIGEST_CONFIG="$HOME/.hermes/digest/digests/$DIGEST_NAME/config.json"
else
    export DIGEST_CONFIG="${DIGEST_CONFIG:-$HOME/.hermes/digest/config.json}"
fi

exec python3 "$REPO_DIR/publish/digest-watchdog.py" "$@"
