#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
APP_HOME="$HOME"

BACKUP_BUCKET="${YOUTUBE_BACKUP_BUCKET:-youtube-monitor-backups-001215999505-cw}"

if [[ "$EUID" -eq 0 ]]; then
    echo "Run as the application user, not root." >&2
    exit 1
fi

usage() {
    echo "Usage: $0 [--monitors|--backups|--all]"
    echo
    echo "Installs systemd units without starting or enabling them."
    exit 1
}

MODE="${1:-}"

case "$MODE" in
    --monitors|--backups|--all)
        ;;
    *)
        usage
        ;;
esac

install_template() {
    local source="$1"
    local destination="$2"

    echo "Installing $destination"

    sed \
        -e "s|@APP_DIR@|$ROOT|g" \
        -e "s|@USER@|$APP_USER|g" \
        -e "s|@GROUP@|$APP_GROUP|g" \
        -e "s|@HOME@|$APP_HOME|g" \
        -e "s|@BUCKET@|$BACKUP_BUCKET|g" \
        "$ROOT/systemd/$source" |
        sudo tee "/etc/systemd/system/$destination" >/dev/null
}

install_timer() {
    local name="$1"

    echo "Installing $name"

    sudo install \
        -m 0644 \
        "$ROOT/systemd/$name" \
        "/etc/systemd/system/$name"
}

if [[ "$MODE" == "--monitors" || "$MODE" == "--all" ]]; then

    echo "Installing monitoring services..."

    install_template \
        "youtube-monitor@.service.in" \
        "youtube-monitor@.service"

    install_template \
        "youtube-report.service.in" \
        "youtube-report.service"

    install_timer "youtube-report.timer"

fi

if [[ "$MODE" == "--backups" || "$MODE" == "--all" ]]; then

    echo "Installing backup services..."

    install_template \
        "youtube-backup@.service.in" \
        "youtube-backup@.service"

    install_timer "youtube-backup-daily.timer"
    install_timer "youtube-backup-weekly.timer"
    install_timer "youtube-backup-monthly.timer"

fi

echo "Reloading systemd..."

sudo systemctl daemon-reload

echo
echo "Deployment complete."
echo "No services or timers were started or enabled."