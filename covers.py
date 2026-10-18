"""Album cover helpers. Only Spotify image hosts are accepted, whatever a payload or API response contains."""
import re
import time
from urllib.parse import urlparse

import requests
from psycopg2.extras import execute_values

OEMBED_URL = "https://open.spotify.com/oembed"
TRACK_ID = re.compile(r"[A-Za-z0-9]{22}")
RETRY_MISSING_DAYS = 7
TARGET_WIDTH = 300


def is_allowed_cover_url(url):
    """True only for https URLs on Spotify's image hosts."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "scdn.co" or host.endswith(".scdn.co") or host == "spotifycdn.com" or host.endswith(".spotifycdn.com")
    )


def pick_cover(images):
    """From a Spotify `album.images` list, the allowed image whose width is closest to 300px (or None)."""
    candidates = [
        i for i in (images or [])
        if isinstance(i, dict) and is_allowed_cover_url(i.get("url"))
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda i: abs((i.get("width") or TARGET_WIDTH) - TARGET_WIDTH))
    return best["url"]


def cover_rows_from_payload(items):
    """(track_id, cover_url) pairs from a recently-played payload; one per track."""
    rows = {}
    for item in items:
        track = item.get("track") or {}
        tid = track.get("id")
        if tid and tid not in rows:
            rows[tid] = pick_cover((track.get("album") or {}).get("images"))
    return [(tid, url) for tid, url in rows.items() if url]


def oembed_cover(track_id):
    """Cover URL via Spotify's keyless oEmbed endpoint, or None."""
    if not TRACK_ID.fullmatch(track_id or ""):
        return None
    try:
        resp = requests.get(
            OEMBED_URL, params={"url": f"https://open.spotify.com/track/{track_id}"}, timeout=10
        )
        if resp.status_code != 200:
            return None
        url = resp.json().get("thumbnail_url")
    except (requests.RequestException, ValueError):
        return None
    return url if is_allowed_cover_url(url) else None


def save_covers(conn, rows):
    """Upsert (track_id, cover_url) rows. A real URL is never overwritten by a miss."""
    if not rows:
        return
    query = """
        INSERT INTO track_covers (track_id, cover_url) VALUES %s
        ON CONFLICT (track_id) DO UPDATE SET
            cover_url  = COALESCE(EXCLUDED.cover_url, track_covers.cover_url),
            fetched_at = now()
    """
    with conn.cursor() as cur:
        execute_values(cur, query, rows)
    conn.commit()


def backfill_covers(conn, limit=200, pause_s=0.2):
    """Look up covers (oEmbed) for played tracks that have none yet. Misses are retried after a week."""
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT DISTINCT p.track_id
            FROM raw_recently_played p
            LEFT JOIN track_covers c ON c.track_id = p.track_id
            WHERE c.track_id IS NULL
               OR (c.cover_url IS NULL AND c.fetched_at < now() - interval '{RETRY_MISSING_DAYS} days')
            LIMIT %s
        """, (int(limit),))
        pending = [r[0] for r in cur.fetchall()]
    rows = []
    for tid in pending:
        rows.append((tid, oembed_cover(tid)))
        time.sleep(pause_s)
    save_covers(conn, rows)
    return len(rows), sum(1 for _, url in rows if url)
