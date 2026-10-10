#!/bin/sh
set -eu

exec python -m easyread serve \
  --host "${PAPERREAD_HOST:-0.0.0.0}" \
  --port "${PAPERREAD_PORT:-8765}"
