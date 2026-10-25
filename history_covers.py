"""Fetch album covers for the songs the Lifetime Wrapped page shows.

Run after import_history.py and dbt:
    python history_covers.py

Covers the overall top songs, every song that was a month's number one, and each year's top songs. Songs that
already have a cover (or were looked up recently) are skipped; the rest go through Spotify's keyless oEmbed
endpoint, a few per second. Safe to run again.
"""
import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

import covers
import wrapped as w

ROOT = Path(__file__).resolve().parent
TOP_OVERALL, TOP_PER_YEAR = 600, 40


def wanted_track_ids(conn):
    df = pd.read_sql(
        "select played_at, track_id, track_name, artist_name, album_name, seconds_played::float as seconds_played, "
        "is_real_play, skipped from dbt_dev.all_plays", conn)
    real = w.real_plays(w.prepare(df))
    ids = set(w.top_songs(real, TOP_OVERALL)["track_id"])
    for year in sorted(real["year"].unique()):
        ids |= set(w.monthly_rulers(real, year)["track_id"])
        ids |= set(w.top_songs(real, TOP_PER_YEAR, year)["track_id"])
    ids |= set(w.milestones(real)["track_id"])
    ids |= set(w.obsessions(real, 15)["track_id"]) | set(w.comfort_songs(real, 5, 25)["track_id"])
    ids |= set(w.forgotten_favourites(real, 40, 365)["track_id"])
    return sorted(ids)


def main():
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    ids = wanted_track_ids(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT track_id FROM track_covers WHERE cover_url IS NOT NULL "
                    "OR fetched_at > now() - interval '%s days'" % covers.RETRY_MISSING_DAYS)
        have = {r[0] for r in cur.fetchall()}
    todo = [t for t in ids if t not in have]
    print(f"songs wanted: {len(ids):,} | already covered: {len(ids) - len(todo):,} | to fetch: {len(todo):,}", flush=True)
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        covers.save_covers(conn, [(t, covers.oembed_cover(t)) for t in chunk])
        print(f"  {min(i + 100, len(todo)):,} / {len(todo):,}", flush=True)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE cover_url IS NOT NULL), count(*) FROM track_covers")
        ok, total = cur.fetchone()
    print(f"track_covers holds {ok:,} covers ({total - ok:,} looked up with none available)")
    conn.close()


if __name__ == "__main__":
    main()
