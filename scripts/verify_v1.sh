#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/data"
export SCOUT_EMAIL_DATA_DIR="$TMP_DIR/data"
export SCOUT_EMAIL_DATABASE_URL="sqlite+aiosqlite:///$TMP_DIR/verify.db"
export SCOUT_EMAIL_SEND_MODE="mock"
export SCOUT_EMAIL_MAPS_LIVE_SMOKE_ENABLED="false"
export MAPS_LIVE_SMOKE_ENABLED="false"

cd "$ROOT/backend"
uv run alembic upgrade head
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -q

cd "$ROOT/browser-worker"
uv run pytest -q

cd "$ROOT"
docker compose config >/dev/null

echo "Scout Email V1 default release verification passed."
