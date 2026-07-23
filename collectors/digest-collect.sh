#!/bin/bash
# Wrapper for collect.py — called by digest-collector no_agent cron
# Exports DIGEST_CONFIG so collect.py finds config.json

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DIGEST_CONFIG="${DIGEST_CONFIG:-$HOME/.hermes/digest/config.json}"

exec python3 "$REPO_DIR/collectors/collect.py" "$@"
