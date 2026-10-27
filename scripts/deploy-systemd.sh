#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
APP_HOME="$HOME"

BACKUP_BUCKET="${YOUTUBE_BACKUP_BUCKET:-youtube-monitor-backups-001215999505-cw}"
PUBLIC_BUCKET="${YOUTUBE_PUBLIC_BUCKET:-youtube-monitor-public-001215999505-cw}"

if [[ "$EUID" -eq 0 ]]; then
    echo "Run as the application user, not root." >&2
    exit 1
fi

usage() {
    echo "Usage: $0 [--monitors|--backups|--publisher|--enable-publishing|--disable-publishing|--all]"
    echo
    echo "Installs systemd units without starting or enabling them."
    exit 1
}

MODE="${1:-}"

case "$MODE" in
    --monitors|--backups|--publisher|--enable-publishing|--disable-publishing|--all)
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
        -e "s|@PUBLIC_BUCKET@|$PUBLIC_BUCKET|g" \
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

if [[ "$MODE" == "--publisher" ||
      "$MODE" == "--enable-publishing" ||
      "$MODE" == "--all" ]]; then

    echo "Installing publishing service..."

    install_template \
        "youtube-publish.service.in" \
        "youtube-publish.service"

fi

# Automatic public dashboard publishing
DROPIN_DIR="/etc/systemd/system/youtube-report.service.d"
DROPIN_FILE="$DROPIN_DIR/publish.conf"

if [[ "$MODE" == "--enable-publishing" ]]; then

    echo "Enabling automatic public dashboard publishing..."

    sudo install -d -m 0755 "$DROPIN_DIR"

    sudo install \
        -m 0644 \
        "$ROOT/systemd/youtube-report-publish.conf" \
        "$DROPIN_FILE"

    echo "Publishing integration installed."

fi

if [[ "$MODE" == "--disable-publishing" ]]; then

    echo "Disabling automatic public dashboard publishing..."

    if [[ -f "$DROPIN_FILE" ]]; then
        sudo rm "$DROPIN_FILE"
    fi

    echo "Publishing integration removed."
    echo "The local dashboard and hourly reporting remain enabled."

fi

echo "Reloading systemd..."

sudo systemctl daemon-reload

echo
echo "Deployment complete."
echo "No services or timers were started or enabled."