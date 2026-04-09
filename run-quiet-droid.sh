#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"

if [[ -z "${OPENAI_BASE_URL:-}" ]]; then
  echo "OPENAI_BASE_URL is not set." >&2
  echo "Example: export OPENAI_BASE_URL=http://localhost:8000/v1" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set." >&2
  exit 1
fi

exec python3 "$SCRIPT_DIR/quiet-droid.py" --base-url $OPENAI_BASE_URL --api-key $OPENAI_API_KEY --model $OPENAI_MODEL
