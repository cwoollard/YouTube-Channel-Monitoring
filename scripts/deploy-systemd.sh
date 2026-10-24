#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" != "--apply" ]]; then
  echo 'Preview only. This script installs systemd unit files but does NOT stop, disable, or start monitors.'
  echo 'Run: bash scripts/deploy-systemd.sh --apply'
  exit 0
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
[[ "$EUID" -ne 0 ]] || { echo 'Run as the application user, not root (sudo is used internally).' >&2; exit 1; }
for name in youtube-monitor@.service youtube-report.service youtube-backup.service; do
  sed -e "s|@APP_DIR@|$ROOT|g" -e "s|@USER@|$APP_USER|g" -e "s|@GROUP@|$APP_GROUP|g" "$ROOT/systemd/$name.in" | sudo tee "/etc/systemd/system/$name" >/dev/null
done
sudo install -m 0644 "$ROOT/systemd/youtube-report.timer" /etc/systemd/system/youtube-report.timer
sudo install -m 0644 "$ROOT/systemd/youtube-backup.timer" /etc/systemd/system/youtube-backup.timer
sudo systemctl daemon-reload
printf 'Installed unit files. Nothing started or stopped.\n'
printf 'IMPORTANT: stop/disable legacy youtube-monitor-stephen/paul/honest services BEFORE enabling template instances.\n'
printf 'Then enable youtube-monitor@stephen, @paul, @honest, @katie, @goodbloke and youtube-report.timer. Optionally enable youtube-backup.timer after configuring backup storage.\n'
