#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p data/paul data/honest data/katie data/goodbloke reports thumbnails backups logs
.venv/bin/python -m compileall -q youtube_channel_monitor_v3.py youtube_channel_analyser.py youtube_comparison_report.py youtube_multi_report.py monitor_channel.py
printf 'Installed in %s. Existing SQLite databases have not been changed.\n' "$ROOT"
printf 'Next: inspect scripts/deploy-systemd.sh before explicitly deploying services.\n'
