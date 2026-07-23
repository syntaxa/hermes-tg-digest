#!/bin/bash
# Wrapper called by digest-generator LLM agent after writing output.md
# Exports DIGEST_CONFIG so digest-publish.py finds config.json

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DIGEST_CONFIG="${DIGEST_CONFIG:-$HOME/.hermes/digest/config.json}"

exec python3 "$REPO_DIR/publish/digest-publish.py" "$@"
