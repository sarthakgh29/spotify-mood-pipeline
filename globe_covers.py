"""Fetch album covers for the song globe: your 2,000 most played songs.

    python globe_covers.py

The globe only shows songs whose cover is known, so this fills track_covers for the songs that are still missing one. Spotify's
keyless oEmbed endpoint is used, one request at a time with a short pause, and a "too many requests" answer makes it wait and
retry instead of recording a miss. A song's other releases are tried too (history songs are merged by title and artist, and an
old release id may have no cover). Songs with no cover anywhere are looked up again after a week. Safe to run again.
"""
import os
import time
from pathlib import Path

import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv

import covers
import wrapped as w

ROOT = Path(__file__).resolve().parent
TOP_SONGS = 2000
PAUSE_S = 0.25
MAX_TRIES_PER_SONG = 3


def get_cover(track_id, session):
    """Cover URL for one track, or None. Waits and retries on HTTP 429."""
    if not covers.TRACK_ID.fullmatch(track_id or ""):
        return None
    for attempt in range(6):
        try:
            r = session.get(covers.OEMBED_URL, params={"url": f"https://open.spotify.com/track/{track_id}"}, timeout=10)
        except requests.RequestException:
            time.sleep(2)
            continue
        if r.status_code == 429:
            time.sleep(min(60, float(r.headers.get("Retry-After", 5 * (attempt + 1)))))
            continue
        if r.status_code != 200:
            return None
        try:
            url = r.json().get("thumbnail_url")
        except ValueError:
            return None
        return url if covers.is_allowed_cover_url(url) else None
    return None


def candidates(real, top=TOP_SONGS):
    """For each of the most played songs: its track ids, the most played release first."""
    songs = w.top_songs(real, top)
    ids = (real.groupby(["song_key", "track_id"]).size().rename("n").reset_index().sort_values("n", ascending=False)
               .groupby("song_key")["track_id"].apply(list))
    return [(row.song_key, row.track_name, ids[row.song_key]) for row in songs.itertuples()]


def main():
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    df = pd.read_sql("select played_at, track_id, track_name, artist_name, album_name, seconds_played::float as seconds_played, "
                     "is_real_play, skipped from dbt_dev.all_plays", conn)
    real = w.real_plays(w.prepare(df))
    cands = candidates(real)
    with conn.cursor() as cur:
        cur.execute("SELECT track_id FROM track_covers WHERE cover_url IS NOT NULL")
        have = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT track_id FROM track_covers WHERE cover_url IS NULL AND fetched_at > now() - interval '%s days'" % covers.RETRY_MISSING_DAYS)
        recent_miss = {r[0] for r in cur.fetchall()}
    todo = [(k, n, ids) for k, n, ids in cands if not any(i in have for i in ids) and ids[0] not in recent_miss]
    print(f"top {len(cands):,} songs | with a cover already: {len(cands) - len(todo) - sum(1 for k, n, ids in cands if ids[0] in recent_miss and not any(i in have for i in ids)):,} | "
          f"to look up: {len(todo):,}", flush=True)

    session, found, missed = requests.Session(), 0, 0
    batch = []
    for n, (key, name, ids) in enumerate(todo, 1):
        url = None
        for tid in ids[:MAX_TRIES_PER_SONG]:
            url = get_cover(tid, session)
            time.sleep(PAUSE_S)
            if url:
                batch.append((tid, url))
                break
        if url:
            found += 1
        else:
            missed += 1
            batch.append((ids[0], None))        # remembered as a miss, retried after a week
        if len(batch) >= 50 or n == len(todo):
            covers.save_covers(conn, batch)
            batch = []
            print(f"  {n:,} / {len(todo):,}  (found {found:,}, none {missed:,})", flush=True)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE cover_url IS NOT NULL), count(*) FROM track_covers")
        ok, total = cur.fetchone()
    print(f"track_covers now holds {ok:,} covers ({total - ok:,} looked up with none available)")
    conn.close()


if __name__ == "__main__":
    main()
