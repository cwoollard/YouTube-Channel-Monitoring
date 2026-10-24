# YouTube Channel Monitoring — v4 development package

A Raspberry Pi-friendly, self-hosted YouTube statistics collector with separate SQLite databases per channel, interactive Plotly reports, channel comparisons, and optional graph exports.

**Repository:** https://github.com/cwoollard/YouTube-Channel-Monitoring

## Current status

This is a **v4 development starter**, based on the working v3.1 monitor, v3.1 analyser, comparison v2, and multi-report generator supplied from the Raspberry Pi. The source files are kept intact to minimise migration risk. The existing Pi services should continue running until a planned cutover.

Configured channels: Stephen J Reid, Paul Messner, Honest Ramble (also Paul Messner), Katie Roams, and Good Bloke Outdoors. The two new channel handles are user-supplied and have not yet been tested against YouTube.

## Development / fresh setup

Requires Python 3.13 and `python3-venv` (Debian: `sudo apt install python3-venv`).

```bash
bash scripts/install.sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python monitor_channel.py katie --print-command
```

To start one channel manually (contacts YouTube and creates its own database):

```bash
.venv/bin/python monitor_channel.py katie
```

To generate reports from available databases:

```bash
.venv/bin/python youtube_multi_report.py --config channels.json --output-dir reports
```

To add export controls to reports (optional; see limitations below):

```bash
.venv/bin/python scripts/add_exports.py reports/channel-*.html
```

The existing nginx config serves `reports/youtube_channel_report.html` at `/` and allows `channel-*.html` files. Adapt the `root` path in `nginx/youtube-monitor.conf` to your installation directory. Keep nginx LAN-only unless you configure authentication and TLS.

## Migrating an existing Raspberry Pi (do not skip)

**Do not run the new monitor instances alongside existing instances pointing to the same SQLite files.**

1. Clone this repository into a *separate directory*, not over the live installation.
2. Review `channels.json`, dependencies, service templates, and the installer.
3. Make a consistent SQLite backup of the live databases before any cutover (`scripts/backup.py` works against a matching config).
4. Preserve the existing data layout. The `stephen`, `paul`, and `honest` database paths are unchanged. For production, copy the new source files into the existing `/home/cwoollard/youtube-monitor` directory only during a planned maintenance window, or point the template service at the existing directory.
5. Install the template unit files with `bash scripts/deploy-systemd.sh --apply` **from the intended production directory**. This installs unit files but does not start or stop anything.
6. Stop and disable the three legacy monitor services; check they are inactive. Then enable/start `youtube-monitor@stephen`, `youtube-monitor@paul`, `youtube-monitor@honest`, `youtube-monitor@katie`, `youtube-monitor@goodbloke`. Start them one at a time to stagger YouTube traffic. Only then enable `youtube-report.timer`.
7. Check `journalctl`, database counts and reports before considering the migration complete.

The template services resolve their paths at deployment time; they are not tied to the original username. The report timer runs at **:50 each hour**. If a monitor starts later than this or has not finished, that hour's report may not include its latest poll.

## Backups

Create SQLite-consistent snapshots (safe with active writers):

```bash
.venv/bin/python scripts/backup.py --config channels.json --dest backups
```

Optional S3 upload, after configuring AWS CLI with a least-privilege identity:

```bash
.venv/bin/python scripts/backup.py --config channels.json --dest backups --s3-uri s3://YOUR-BUCKET/youtube-monitor/
```

Test a restore **into a new directory**:

```bash
.venv/bin/python scripts/restore.py backups/youtube-monitor-YYYYMMDDTHHMMSSZ.tar.gz --output /tmp/yt-restore-test
```

The starter backup contains SQLite databases and `channels.json`. **It does not yet archive historical thumbnail images or implement retention.** An optional daily backup timer is included but must be enabled deliberately after reviewing destination and credentials. Do not treat S3 backups as configured until IAM, lifecycle policies, encryption and scheduled uploads have been set up and a restore has been tested.

To enable optional daily backups after configuring the destination, install the systemd units and run `sudo systemctl enable --now youtube-backup.timer`. The default is local backups only. For S3, copy `.env.example` to `.env`, set `YOUTUBE_BACKUP_S3_URI`, `chmod 600 .env`, and configure an AWS CLI identity with limited bucket permissions. **No retention pruning is performed yet**; monitor free disk space and configure S3 lifecycle policies.

## Export controls

`add_exports.py` adds client-side PNG, SVG, and self-contained HTML buttons to Plotly graphs in generated channel report files. Export uses the currently rendered graph. **This is a first-pass implementation:** validate in Safari and Chromium, especially on the comparison page, before sharing files. The multi-report generator automatically injects export controls each time reports are regenerated. Browser behaviour should be validated in Safari and Chromium before sharing.

## Configuration

`channels.json` contains stable channel IDs, display names, creators, YouTube URLs, database paths and polling options. Add another channel by adding a unique ID and database path. `monitor_channel.py` is a thin wrapper around the existing v3.1 script, preserving the SQLite schema.

## Security

Do not commit SQLite databases, thumbnails, reports, `.env` files, AWS credentials, SSH keys, or personal data. `.gitignore` excludes generated files by default. Review changes with `git status` before pushing. The report server does not implement authentication.

## Planned follow-ups

- Validate new channel handles and initial polling under conservative request limits.
- Add integration tests for report exports and comparison interactions.
- Validate browser exports on Safari and Chromium.
- Add scheduled S3 backup/retention and restore verification.
- Implement per-channel health reporting and clearer failed-observation counts.
