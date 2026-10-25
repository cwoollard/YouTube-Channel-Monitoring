# YouTube Monitor v4.1 backup upgrade

Copy `scripts/backup.py`, `scripts/restore.py`, `scripts/backup-run.sh`, and `tests/test_backup.py` into the **monitoring** repository. Keep existing v4 files backed up until tests pass. Copy the systemd files into its `systemd/` directory. Do not deploy the timers until v4 production cutover is complete.

## Local smoke test on Raspberry Pi (no AWS writes)

```bash
cd ~/youtube-monitor-v4
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/backup.py --config channels.json --thumbnail-dir thumbnails --dest backups --allow-missing katie --allow-missing goodbloke
BACKUP=$(ls -t backups/youtube-monitor-daily-*.tar.gz | head -1)
.venv/bin/python scripts/restore.py "$BACKUP" --verify-only
.venv/bin/python scripts/restore.py "$BACKUP" --output "/tmp/youtube-restore-$(date +%s)"
```

`--allow-missing` is **only for the v4 staging period** when Katie/Good Bloke may not have databases yet. Production backup-run.sh deliberately has no such exception: all configured databases must exist. Do not enable timers until all five are present. The source directory `thumbnails/` must exist.

## First real S3 upload (manual, after staging is complete)

```bash
cd ~/youtube-monitor-v4
.venv/bin/python scripts/backup.py --config channels.json --thumbnail-dir thumbnails --dest backups --tier daily --profile youtube-backup --s3-uri s3://youtube-monitor-backups-001215999505-cw/daily/
```

Verify S3 using the Mac's `personal-admin` profile; the Pi uploader is intentionally write-only. Download a backup using the Mac admin identity and run `restore.py --verify-only` on the downloaded archive.

## Systemd deployment (only after v4 production cutover)

**Warning:** existing v4 `youtube-backup.service` / `youtube-backup.timer` may exist. Do not run two backup schedules. Inspect and disable the legacy backup timer before enabling these new timers. Keep monitor/report services unchanged.

On the Pi as `cwoollard`, generate a unit from the template:

```bash
cd ~/youtube-monitor-v4
sed -e "s|@APP_DIR@|$PWD|g" -e "s|@USER@|$(id -un)|g" -e "s|@GROUP@|$(id -gn)|g" -e "s|@HOME@|$HOME|g" -e 's|@BUCKET@|youtube-monitor-backups-001215999505-cw|g' systemd/youtube-backup@.service.in | sudo tee /etc/systemd/system/youtube-backup@.service >/dev/null
sudo install -m 0644 systemd/youtube-backup-{daily,weekly,monthly}.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl cat youtube-backup@.service
```

After ensuring the old timer is disabled and all databases exist:

```bash
sudo systemctl enable --now youtube-backup-daily.timer youtube-backup-weekly.timer youtube-backup-monthly.timer
systemctl list-timers --all | grep youtube-backup
sudo systemctl start youtube-backup@daily.service
journalctl -u youtube-backup@daily.service -n 40 --no-pager
```

`backup-run.sh` requires `flock` (util-linux) and a Pi AWS profile named `youtube-backup`. The systemd unit runs as the Pi account to access its credentials. Local retention is 7 days per tier; S3 lifecycle handles remote retention. S3 upload errors retain the local archive for recovery.

## Limitations and operational notes

- SQLite database snapshots are consistent, but thumbnails copied during active monitoring are not an atomic multi-file snapshot. Historical thumbnails are usually immutable; verify application behaviour before relying on this for a point-in-time image.
- S3 upload success is checked via AWS CLI exit status, not a remote read-back, because the Pi identity is write-only. Perform periodic independent download/restore drills using your Mac administrator identity.
- Archives are fully verified locally before upload; verification extracts them temporarily and needs free disk space. Check disk space on the Pi before enabling scheduled jobs.
- `backup.py` includes all configured channel databases; a missing database fails by default. For staging, explicitly pass `--allow-missing <channel-id>`.
- Restore output uses `databases/<channel-id>.sqlite3`; consult `channels.json` to map restored snapshots back to their live locations. It never overwrites live databases.
