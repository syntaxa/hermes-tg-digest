#!/bin/bash
# Wrapper called by digest-generator LLM agent after writing output.md
export DIGEST_CONFIG=/home/hermes/.hermes/digest/config.json
exec python3 /home/hermes/hermes-tg-digest/publish/digest-publish.py "$@"
