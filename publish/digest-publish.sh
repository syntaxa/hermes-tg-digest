#!/bin/bash
# Wrapper called by digest-generator LLM agent after writing output.md
exec python3 /home/hermes/hermes-tg-digest/publish/digest-publish.py "$@"
