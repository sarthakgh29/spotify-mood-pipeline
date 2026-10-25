"""Load a Spotify "Extended streaming history" export into raw_streaming_history.

    python import_history.py Spotify_Extended          (the unzipped folder)
    python import_history.py my_export.zip             (or the zip itself)

Only the Streaming_History_Audio_*.json files are read, and only music rows (a spotify:track: URI). Podcasts,
audiobooks, video files and rows without a track are skipped. The export also holds your IP address and country
for every play: those fields are dropped here and never stored. Safe to run again: a play that is already in the
table (same played_at and track_id) is left alone.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

import os

ROOT = Path(__file__).resolve().parent
AUDIO_FILE = re.compile(r"Streaming_History_Audio_.*\.json$")
TRACK_URI = re.compile(r"^spotify:track:([A-Za-z0-9]{22})$")
BATCH = 5000

INSERT = """
    INSERT INTO raw_streaming_history
        (played_at, track_id, track_name, artist_name, album_name, ms_played,
         reason_start, reason_end, skipped, shuffle, offline, incognito, platform)
    VALUES %s
    ON CONFLICT (played_at, track_id) DO NOTHING
"""


def read_json_files(source):
    """Yield (file name, list of records) for every audio-history file in a folder or a zip."""
    source = Path(source)
    if source.is_dir():
        for path in sorted(source.rglob("*.json")):
            if AUDIO_FILE.search(path.name):
                yield path.name, json.loads(path.read_text(encoding="utf-8"))
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            for name in sorted(z.namelist()):
                if AUDIO_FILE.search(name):
                    yield name, json.loads(z.read(name).decode("utf-8"))
    else:
        raise SystemExit(f"{source} is neither a folder nor a zip file")


def platform_name(raw):
    """'Android OS 14 API 34 (samsung, ...)' -> 'android'. The long string can carry device details."""
    words = (raw or "").split()
    return words[0].lower() if words else None


def to_row(rec):
    """One export record -> a table row, or None if it is not a music play. ip_addr and conn_country are left out."""
    m = TRACK_URI.match(rec.get("spotify_track_uri") or "")
    if not m or not rec.get("ts"):
        return None
    return (rec["ts"], m.group(1), rec.get("master_metadata_track_name"), rec.get("master_metadata_album_artist_name"),
            rec.get("master_metadata_album_album_name"), int(rec.get("ms_played") or 0),
            rec.get("reason_start"), rec.get("reason_end"), rec.get("skipped"), rec.get("shuffle"),
            rec.get("offline"), rec.get("incognito_mode"), platform_name(rec.get("platform")))


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM raw_streaming_history")
    before = cur.fetchone()[0]

    seen = skipped = 0
    for name, records in read_json_files(argv[1]):
        rows = []
        for rec in records:
            row = to_row(rec)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
        for i in range(0, len(rows), BATCH):
            execute_values(cur, INSERT, rows[i:i + BATCH])
        conn.commit()
        seen += len(rows)
        print(f"{name}: {len(rows):,} music plays", flush=True)

    cur.execute("SELECT count(*), min(played_at), max(played_at) FROM raw_streaming_history")
    after, first, last = cur.fetchone()
    print(f"\nread {seen:,} music plays ({skipped:,} non-music rows skipped); "
          f"{after - before:,} new, {seen - (after - before):,} already there")
    print(f"raw_streaming_history: {after:,} plays, {first:%d %b %Y} to {last:%d %b %Y}")
    conn.close()


if __name__ == "__main__":
    main(sys.argv)
