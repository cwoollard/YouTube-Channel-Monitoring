#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
args=(--config "$ROOT/channels.json" --dest "$ROOT/backups")
if [[ -n "${YOUTUBE_BACKUP_S3_URI:-}" ]]; then
  args+=(--s3-uri "$YOUTUBE_BACKUP_S3_URI")
fi
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/backup.py" "${args[@]}"
