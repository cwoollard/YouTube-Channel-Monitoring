#!/usr/bin/env python3
"""Monitor a YouTube channel for changes and build a time-series dataset.

Version 3: preserves v2 data and records channel-listing variants independently.

This script is designed to be left running on a Mac.

It monitors the most recent N public videos on a channel and periodically records:
  - observation timestamp
  - current views, likes and comments
  - title
  - thumbnail image hash
  - published date, duration and basic metadata

It also detects and records:
  - title changes
  - thumbnail image changes
  - newly discovered videos

Data is stored in SQLite so the script can be safely interrupted and resumed.
CSV exports are refreshed after each polling cycle.

Examples:
  python3 youtube_channel_monitor.py 'https://www.youtube.com/watch?v=qGJZCsoN1pI'
  python3 youtube_channel_monitor.py 'https://www.youtube.com/watch?v=qGJZCsoN1pI' --recent 20 --interval 3600
  python3 youtube_channel_monitor.py 'https://www.youtube.com/watch?v=qGJZCsoN1pI' --once

Install:
  python3 -m pip install -U yt-dlp

Optional browser cookies (only use if YouTube requires them):
  --cookies-from-browser safari
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yt_dlp
except ImportError:
    print(
        "yt-dlp is not installed. Install it with: python3 -m pip install -U yt-dlp",
        file=sys.stderr,
    )
    raise SystemExit(2)


class RateLimited(RuntimeError):
    """Stop the polling cycle when YouTube explicitly signals rate limiting."""


class YoutubeErrorTracker:
    def __init__(self):
        self.rate_limited = False

    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        if "rate-limited" in message.lower() or "http error 429" in message.lower() or "too many requests" in message.lower():
            self.rate_limited = True
        print(message, file=sys.stderr)


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_from_epoch(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or not value:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def clean(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items() if not str(k).startswith("__")}
    return str(value)


def extract_one(url: str, opts: dict[str, Any]) -> dict[str, Any] | None:
    tracker = YoutubeErrorTracker()
    run_opts = dict(opts, logger=tracker, retries=0, extractor_retries=0)
    with yt_dlp.YoutubeDL(run_opts) as ydl:
        result = ydl.extract_info(url, download=False)
    if tracker.rate_limited:
        raise RateLimited("YouTube rate limit detected")
    return result


def find_channel_url(info: dict[str, Any]) -> str | None:
    for key in ("channel_url", "uploader_url"):
        value = info.get(key)
        if isinstance(value, str) and "youtube.com/" in value:
            value = value.rstrip("/")
            return value if value.endswith("/videos") else value + "/videos"
    return None


def list_channel_videos(
    channel_videos_url: str,
    opts: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    list_opts = dict(opts)
    list_opts["extract_flat"] = True
    list_opts["playlistend"] = limit
    list_opts["ignoreerrors"] = True
    list_opts["retries"] = 0
    list_opts["extractor_retries"] = 0
    tracker = YoutubeErrorTracker()
    list_opts["logger"] = tracker
    with yt_dlp.YoutubeDL(list_opts) as ydl:
        result = ydl.extract_info(channel_videos_url, download=False)
    if tracker.rate_limited:
        raise RateLimited("YouTube rate limit detected during channel listing")
    if not result:
        raise RuntimeError("No channel listing returned")

    entries: list[dict[str, Any]] = []
    for entry in result.get("entries") or []:
        if entry:
            entries.append(entry)
            if len(entries) >= limit:
                break
    return entries


def choose_thumbnail_url(info: dict[str, Any]) -> str | None:
    # Prefer the main thumbnail field. Fall back to the largest URL yt-dlp exposes.
    thumb = info.get("thumbnail")
    if isinstance(thumb, str) and thumb:
        return thumb

    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list):
        urls = [x.get("url") for x in thumbs if isinstance(x, dict) and isinstance(x.get("url"), str)]
        if urls:
            # Usually the last entry is the highest-quality thumbnail.
            return urls[-1]
    return None


def download_thumbnail_hash(url: str | None, timeout: int = 20) -> tuple[str | None, int | None]:
    if not url:
        return None, None

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"    Thumbnail download failed: {exc}", file=sys.stderr)
        return None, None

    if not data:
        return None, 0

    return hashlib.sha256(data).hexdigest(), len(data)


def normalise_video(info: dict[str, Any]) -> dict[str, Any]:
    video_id = info.get("id")
    return {
        "video_id": video_id,
        "title": info.get("title"),
        "url": info.get("webpage_url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None),
        "published": iso_from_epoch(info.get("timestamp")),
        "upload_date": info.get("upload_date"),
        "duration_seconds": info.get("duration"),
        "duration_string": info.get("duration_string"),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id") or info.get("uploader_id"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "description": info.get("description"),
        "categories": info.get("categories"),
        "tags": info.get("tags"),
        "language": info.get("language"),
        "availability": info.get("availability"),
        "live_status": info.get("live_status"),
        "was_live": info.get("was_live"),
        "is_live": info.get("is_live"),
        "age_limit": info.get("age_limit"),
    }


def save_thumbnail_variant(url: str | None, digest: str | None, directory: Path, timeout: int = 20) -> None:
    """Archive first-seen thumbnail bytes; failures never interrupt monitoring."""
    if not url or not digest:
        return
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (digest + ".img")
    if target.exists():
        return
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() == digest:
            target.write_bytes(data)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"    Thumbnail archive failed: {exc}", file=sys.stderr)


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            url TEXT,
            channel TEXT,
            channel_id TEXT,
            channel_url TEXT,
            published TEXT,
            upload_date TEXT,
            duration_seconds REAL,
            duration_string TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            video_id TEXT NOT NULL,
            title TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            thumbnail_hash TEXT,
            thumbnail_bytes INTEGER,
            thumbnail_url TEXT,
            UNIQUE(observed_at, video_id),
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_at TEXT NOT NULL,
            video_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            details TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_observations_video_time ON observations(video_id, observed_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_changes_video_time ON changes(video_id, changed_at)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS listing_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        observed_at TEXT NOT NULL,
        video_id TEXT NOT NULL,
        listing_title TEXT,
        detail_title TEXT,
        listing_thumbnail_url TEXT,
        detail_thumbnail_hash TEXT,
        UNIQUE(observed_at, video_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listing_video_time ON listing_observations(video_id, observed_at)")
    conn.commit()
    return conn


def get_latest_observation(conn: sqlite3.Connection, video_id: str) -> sqlite3.Row | None:
    """Return the most recent already-committed observation for a video."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT observed_at, title, views, likes, comments, thumbnail_hash, thumbnail_bytes,
               thumbnail_url
        FROM observations
        WHERE video_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()


def upsert_video(conn: sqlite3.Connection, video: dict[str, Any], observed_at: str) -> bool:
    existing = conn.execute(
        "SELECT video_id FROM videos WHERE video_id = ?", (video["video_id"],)
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE videos
            SET url = ?, channel = ?, channel_id = ?, channel_url = ?, published = ?,
                upload_date = ?, duration_seconds = ?, duration_string = ?, last_seen = ?
            WHERE video_id = ?
            """,
            (
                video.get("url"), video.get("channel"), video.get("channel_id"),
                video.get("channel_url"), video.get("published"), video.get("upload_date"),
                video.get("duration_seconds"), video.get("duration_string"), observed_at,
                video["video_id"],
            ),
        )
        return False

    conn.execute(
        """
        INSERT INTO videos (
            video_id, url, channel, channel_id, channel_url, published, upload_date,
            duration_seconds, duration_string, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video["video_id"], video.get("url"), video.get("channel"), video.get("channel_id"),
            video.get("channel_url"), video.get("published"), video.get("upload_date"),
            video.get("duration_seconds"), video.get("duration_string"), observed_at, observed_at,
        ),
    )
    return True


def record_change(
    conn: sqlite3.Connection,
    changed_at: str,
    video_id: str,
    change_type: str,
    old_value: Any,
    new_value: Any,
    details: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO changes (changed_at, video_id, change_type, old_value, new_value, details)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            changed_at,
            video_id,
            change_type,
            None if old_value is None else str(old_value),
            None if new_value is None else str(new_value),
            details,
        ),
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_csvs(conn: sqlite3.Connection, prefix: Path) -> None:
    conn.row_factory = sqlite3.Row

    observations = [dict(row) for row in conn.execute(
        """
        SELECT o.observed_at, o.video_id, v.published, o.title, o.views, o.likes, o.comments,
               o.thumbnail_hash, o.thumbnail_bytes, o.thumbnail_url, v.url
        FROM observations o
        JOIN videos v ON v.video_id = o.video_id
        ORDER BY o.observed_at, o.video_id
        """
    )]
    write_csv(
        prefix.with_name(prefix.name + "_observations.csv"),
        observations,
        [
            "observed_at", "video_id", "published", "title", "views", "likes", "comments",
            "thumbnail_hash", "thumbnail_bytes", "thumbnail_url", "url",
        ],
    )

    changes = [dict(row) for row in conn.execute(
        "SELECT changed_at, video_id, change_type, old_value, new_value, details FROM changes ORDER BY changed_at"
    )]
    write_csv(
        prefix.with_name(prefix.name + "_changes.csv"),
        changes,
        ["changed_at", "video_id", "change_type", "old_value", "new_value", "details"],
    )

    listing = [dict(row) for row in conn.execute(
        "SELECT observed_at, video_id, listing_title, detail_title, listing_thumbnail_url, detail_thumbnail_hash FROM listing_observations ORDER BY observed_at, video_id"
    )]
    write_csv(prefix.with_name(prefix.name + "_listing_variants.csv"), listing,
              ["observed_at", "video_id", "listing_title", "detail_title", "listing_thumbnail_url", "detail_thumbnail_hash"])

    latest = [dict(row) for row in conn.execute(
        """
        SELECT v.video_id, v.published, v.duration_seconds, v.duration_string,
               o.observed_at, o.title, o.views, o.likes, o.comments,
               o.thumbnail_hash, o.thumbnail_bytes, o.thumbnail_url, v.url
        FROM videos v
        JOIN observations o ON o.id = (
            SELECT o2.id FROM observations o2
            WHERE o2.video_id = v.video_id
            ORDER BY o2.observed_at DESC LIMIT 1
        )
        ORDER BY v.published DESC
        """
    )]
    write_csv(
        prefix.with_name(prefix.name + "_latest.csv"),
        latest,
        [
            "video_id", "published", "duration_seconds", "duration_string", "observed_at",
            "title", "views", "likes", "comments", "thumbnail_hash", "thumbnail_bytes",
            "thumbnail_url", "url",
        ],
    )


def poll_once(
    conn: sqlite3.Connection,
    channel_url: str,
    ydl_opts: dict[str, Any],
    recent: int,
    request_delay: float,
    thumbnail_timeout: int,
    thumbnail_dir: Path,
) -> tuple[int, int, int]:
    observed_at = utc_now()
    entries = list_channel_videos(channel_url, ydl_opts, recent)
    print(f"Found {len(entries)} recent videos to inspect.")

    new_videos = 0
    title_changes = 0
    thumbnail_changes = 0

    for index, entry in enumerate(entries, start=1):
        video_id = entry.get("id")
        if not video_id:
            continue
        # Always fetch the single watch URL, never a playlist or channel URL from a flat entry.
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[{index}/{len(entries)}] {entry.get('title') or video_id}")

        try:
            info = extract_one(video_url, ydl_opts)
        except RateLimited:
            raise
        except Exception as exc:
            print(f"    Warning: failed to fetch {video_id}: {exc}", file=sys.stderr)
            if index < len(entries):
                time.sleep(max(0.0, request_delay))
            continue

        if not info:
            if index < len(entries):
                time.sleep(max(0.0, request_delay))
            continue

        video = normalise_video(info)
        thumb_url = choose_thumbnail_url(info)
        thumb_hash, thumb_bytes = download_thumbnail_hash(thumb_url, timeout=thumbnail_timeout)
        save_thumbnail_variant(thumb_url, thumb_hash, thumbnail_dir, timeout=thumbnail_timeout)

        # Capture the previous state BEFORE writing anything for this poll.
        # This makes change detection explicit and robust to any current-cycle writes.
        previous = get_latest_observation(conn, video_id)

        is_new = upsert_video(conn, video, observed_at)
        if is_new:
            new_videos += 1
            record_change(
                conn,
                observed_at,
                video_id,
                "new_video",
                None,
                video.get("title"),
                "Video first observed by this monitor",
            )
            print("    NEW VIDEO")

        if previous is not None:
            if previous["title"] != video.get("title") and video.get("title") is not None:
                title_changes += 1
                record_change(
                    conn,
                    observed_at,
                    video_id,
                    "title_changed",
                    previous["title"],
                    video.get("title"),
                    "previous_observation=" + str(previous["observed_at"]),
                )
                print(f"    TITLE CHANGED: {previous['title']} -> {video.get('title')}")

            if (
                previous["thumbnail_hash"]
                and thumb_hash
                and previous["thumbnail_hash"] != thumb_hash
            ):
                thumbnail_changes += 1
                record_change(
                    conn,
                    observed_at,
                    video_id,
                    "thumbnail_changed",
                    previous["thumbnail_hash"],
                    thumb_hash,
                    f"old_bytes={previous['thumbnail_bytes']}; new_bytes={thumb_bytes}; "
                    f"previous_observation={previous['observed_at']}",
                )
                print("    THUMBNAIL CHANGED")

        conn.execute(
            """
            INSERT OR IGNORE INTO observations (
                observed_at, video_id, title, views, likes, comments,
                thumbnail_hash, thumbnail_bytes, thumbnail_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at,
                video_id,
                video.get("title"),
                video.get("views"),
                video.get("likes"),
                video.get("comments"),
                thumb_hash,
                thumb_bytes,
                thumb_url,
            ),
        )
        conn.execute("""INSERT OR IGNORE INTO listing_observations
            (observed_at, video_id, listing_title, detail_title, listing_thumbnail_url, detail_thumbnail_hash)
            VALUES (?, ?, ?, ?, ?, ?)""", (
            observed_at, video_id, entry.get("title"), video.get("title"),
            choose_thumbnail_url(entry), thumb_hash,
        ))
        if entry.get("title") and entry.get("title") != video.get("title"):
            print(f"    LISTING VARIANT: {entry.get('title')} | detail: {video.get('title')}")
        conn.commit()

        if index < len(entries):
            time.sleep(max(0.0, request_delay))

    return new_videos, title_changes, thumbnail_changes


def resolve_channel(seed_url: str, ydl_opts: dict[str, Any]) -> tuple[str, str | None, str | None]:
    print(f"Resolving: {seed_url}")
    parsed = urlparse(seed_url)
    path = parsed.path.rstrip("/")
    # Channel handles/IDs already identify the channel. Do NOT extract the whole
    # channel merely to resolve its name; on large channels this can enumerate
    # hundreds of videos and trigger rate limiting.
    if parsed.netloc.lower() in ("youtube.com", "www.youtube.com", "m.youtube.com") and (
        path.startswith("/@") or path.startswith("/channel/") or path.startswith("/c/") or path.startswith("/user/")
    ):
        channel_url = f"https://www.youtube.com{path}"
        if not channel_url.endswith("/videos"):
            channel_url += "/videos"
        return channel_url, path.split("/")[1], None

    # Video links can be resolved with one metadata request.
    info = extract_one(seed_url, ydl_opts)
    if not info:
        raise RuntimeError("No metadata returned from the supplied video URL.")
    channel_url = find_channel_url(info)
    if not channel_url:
        raise RuntimeError("Could not identify channel from video URL")
    return channel_url, info.get("channel") or info.get("uploader"), info.get("channel_id") or info.get("uploader_id")


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously monitor a YouTube channel's recent videos.")
    parser.add_argument("url", help="A YouTube video URL or channel URL used to identify the channel")
    parser.add_argument(
        "--recent",
        type=int,
        default=20,
        help="Number of newest videos to inspect on each poll (default: 20)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3600,
        help="Seconds between polls (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds between individual video requests (default: 1.5)",
    )
    parser.add_argument(
        "--thumbnail-timeout",
        type=int,
        default=20,
        help="Seconds allowed for each thumbnail download (default: 20)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll and exit",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="Use browser cookies, e.g. safari, chrome, firefox",
    )
    parser.add_argument(
        "--db",
        default="youtube_channel_monitor.sqlite3",
        help="SQLite database path (default: youtube_channel_monitor.sqlite3)",
    )
    parser.add_argument(
        "--output",
        default="youtube_channel_monitor",
        help="CSV output filename prefix (default: youtube_channel_monitor)",
    )
    parser.add_argument("--rate-limit-backoff", type=int, default=7200,
                        help="Seconds to pause after YouTube rate limits requests (default: 7200)")
    parser.add_argument("--thumbnail-dir", default=None,
                        help="Directory for unique thumbnail image files (default: OUTPUT_thumbnails)")
    args = parser.parse_args()

    if args.recent < 1:
        parser.error("--recent must be at least 1")
    if args.interval < 60 and not args.once:
        parser.error("--interval must be at least 60 seconds for continuous monitoring")

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if args.cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (args.cookies_from_browser,)

    try:
        channel_url, channel_name, channel_id = resolve_channel(args.url, ydl_opts)
    except Exception as exc:
        print(f"Failed to resolve channel: {exc}", file=sys.stderr)
        return 1

    print(f"Channel : {channel_name or 'Unknown'}")
    print(f"ID      : {channel_id or 'unknown'}")
    print(f"Videos  : {channel_url}")
    print(f"Watching: newest {args.recent} videos")
    print(f"Interval: {args.interval:g} seconds")
    print()

    db_path = Path(args.db).expanduser().resolve()
    output_prefix = Path(args.output).expanduser().resolve()
    conn = init_db(db_path)
    thumbnail_dir = Path(args.thumbnail_dir).expanduser().resolve() if args.thumbnail_dir else output_prefix.with_name(output_prefix.name + "_thumbnails")

    try:
        while True:
            cycle_started = time.monotonic()
            print(f"=== Poll started {utc_now()} ===")
            try:
                new_videos, title_changes, thumbnail_changes = poll_once(
                    conn,
                    channel_url,
                    ydl_opts,
                    args.recent,
                    args.delay,
                    args.thumbnail_timeout,
                    thumbnail_dir,
                )
                export_csvs(conn, output_prefix)
                print(
                    f"Cycle complete: {new_videos} new videos, "
                    f"{title_changes} title changes, {thumbnail_changes} thumbnail changes."
                )
                print(f"Database: {db_path}")
                print(f"Exports : {output_prefix.parent / (output_prefix.name + '_observations.csv')}")
                print(f"          {output_prefix.parent / (output_prefix.name + '_changes.csv')}")
                print(f"          {output_prefix.parent / (output_prefix.name + '_latest.csv')}")
            except KeyboardInterrupt:
                raise
            except RateLimited as exc:
                print(f"RATE LIMITED: {exc}; backing off {args.rate_limit_backoff}s", file=sys.stderr)
                if args.once:
                    break
                time.sleep(max(3600, args.rate_limit_backoff))
                continue
            except Exception as exc:
                print(f"Poll failed: {exc}", file=sys.stderr)

            if args.once:
                break

            elapsed = time.monotonic() - cycle_started
            sleep_for = max(60.0, args.interval - elapsed)
            next_time = datetime.now().astimezone().timestamp() + sleep_for
            next_dt = datetime.fromtimestamp(next_time).astimezone()
            print(f"Next poll: {next_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print("Press Ctrl-C to stop safely.\n")
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\nStopped. All committed observations are safely stored in SQLite.")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
