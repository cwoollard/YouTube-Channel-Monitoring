#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIER="${1:-daily}"
case "$TIER" in daily|weekly|monthly) ;; *) echo "Invalid tier: $TIER" >&2; exit 2;; esac
BUCKET="${YOUTUBE_BACKUP_BUCKET:?Set YOUTUBE_BACKUP_BUCKET in the service environment}"
PROFILE="${YOUTUBE_BACKUP_PROFILE:-youtube-backup}"
# Serialise across all three timers and manual invocations.
mkdir -p "$ROOT/backups"
exec 9>"$ROOT/backups/.backup.lock"
flock -n 9 || { echo 'Another backup is running' >&2; exit 1; }
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/backup.py" \
  --config "$ROOT/channels.json" \
  --thumbnail-dir "$ROOT/thumbnails" \
  --dest "$ROOT/backups" \
  --tier "$TIER" \
  --retain-local-days "${YOUTUBE_LOCAL_RETENTION_DAYS:-7}" \
  --profile "$PROFILE" \
  --s3-uri "s3://$BUCKET/$TIER/"
