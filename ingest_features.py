"""Fetch audio features (valence, energy, ...) from ReccoBeats for every track in raw_recently_played.

Uses the batch endpoint with Spotify track IDs directly, 40 per request (larger batches return HTTP 400).
Multiple IDs are sent as a repeated parameter (?ids=A&ids=B), the form ReccoBeats' docs use.

Usage:
    python ingest_features.py --probe           # test the request formats on 20 tracks, write nothing
    python ingest_features.py                   # fetch tracks not stored yet, plus old misses
    python ingest_features.py --limit 80        # cap how many tracks are fetched in one run
    python ingest_features.py --retry-misses    # also retry every stored miss, regardless of age
    python ingest_features.py --refresh-found   # fetch tracks that already have features again
    python ingest_features.py --history         # look up the tracks of the imported Spotify history (most played first)
    python ingest_features.py --history --limit 500   # only the 500 most played history tracks
"""
import argparse
import json
import os
import re
import time

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

BASE_URL = "https://api.reccobeats.com/v1"
BATCH_PATH = "/audio-features"
BATCH_PARAM = "ids"
# "repeat" -> ?ids=A&ids=B (documented form).  "comma" -> ?ids=A,B  (set RECCOBEATS_BATCH_STYLE=comma to switch)
BATCH_STYLE = os.getenv("RECCOBEATS_BATCH_STYLE", "repeat")
BATCH_SIZE = 40
PAUSE_S = 0.5
RETRY_NOT_FOUND_DAYS = int(os.getenv("RECCOBEATS_RETRY_DAYS", "3"))

SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}")
SPOTIFY_URL_ID = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?track/|spotify:track:)([A-Za-z0-9]{22})")


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def http_get(path, params=None, retries=3):
    """GET with 429 / Retry-After handling. Returns a Response, or None if the network keeps failing."""
    url = f"{BASE_URL}{path}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=20)
        except requests.RequestException as exc:
            print(f"  network error: {exc}")
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 429:
            try:
                wait = int(float(resp.headers.get("Retry-After", "5")))
            except ValueError:
                wait = 5
            print(f"  rate limited, waiting {wait}s")
            time.sleep(min(wait, 60))
            continue
        return resp
    return None


def extract_items(payload):
    """Return a list of records, or None if the payload shape isn't recognised.
    An empty list is a legitimate answer ('none of these tracks are known')."""
    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        payload = payload["content"]
    elif isinstance(payload, dict) and "valence" in payload:
        payload = [payload]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return None


def candidate_ids(item):
    """Every Spotify track ID a returned record points at (explicit fields first, then the Spotify URL(s) in href).
    Order of results is never relied on, so records are matched to requests through these IDs."""
    found = []
    for key in ("trackId", "spotifyId", "spotify_id"):
        value = item.get(key)
        if isinstance(value, str) and SPOTIFY_ID.fullmatch(value):
            found.append(value)
    href = item.get("href")
    if isinstance(href, str):
        found.extend(SPOTIFY_URL_ID.findall(href))
    return found


def spotify_id_of(item):
    ids = candidate_ids(item)
    return ids[0] if ids else None


def batch_params(ids):
    if BATCH_STYLE == "comma":
        return {BATCH_PARAM: ",".join(ids)}
    return [(BATCH_PARAM, i) for i in ids]


def resolve_uuid_map(batch):
    """ReccoBeats UUID -> Spotify ID for a batch, through the documented /track lookup (its href holds the
    Spotify URL). Used when audio-feature records only carry ReccoBeats' own id."""
    resp = http_get("/track", params=batch_params(batch))
    if resp is None or resp.status_code != 200:
        return {}
    try:
        items = extract_items(resp.json())
    except ValueError:
        return {}
    wanted, out = set(batch), {}
    for item in items or []:
        uuid = item.get("id")
        hits = [c for c in candidate_ids(item) if c in wanted]
        if isinstance(uuid, str) and hits:
            out[uuid] = hits[0]
    return out


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_features(item):
    """Feature dict, or None if valence/energy are missing or outside 0-1."""
    if not item:
        return None
    valence, energy = _num(item.get("valence")), _num(item.get("energy"))
    if valence is None or energy is None or not (0 <= valence <= 1 and 0 <= energy <= 1):
        return None
    return {
        "valence": valence,
        "energy": energy,
        "danceability": _num(item.get("danceability")),
        "acousticness": _num(item.get("acousticness")),
        "tempo": _num(item.get("tempo")),
        "instrumentalness": _num(item.get("instrumentalness")),
        "liveness": _num(item.get("liveness")),
        "loudness": _num(item.get("loudness")),
        "speechiness": _num(item.get("speechiness")),
        "key": _int(item.get("key")),
        "mode": _int(item.get("mode")),
        "isrc": item.get("isrc") if isinstance(item.get("isrc"), str) else None,
    }


def process_batch(batch):
    """Returns rows ready to store, or None if the batch failed and must NOT be saved (so it is retried later).
    A track the API genuinely doesn't return is stored as 'not_found'."""
    resp = http_get(BATCH_PATH, params=batch_params(batch))
    if resp is None:
        print("  no response, batch skipped")
        return None
    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}, batch skipped: {resp.text[:200]}")
        return None
    try:
        items = extract_items(resp.json())
    except ValueError:
        items = None
    if items is None:
        print("  unrecognised response shape, batch skipped. Run --probe to inspect it.")
        return None

    wanted = set(batch)
    by_id, unmapped = {}, []
    for item in items:
        hits = [c for c in candidate_ids(item) if c in wanted]
        if hits:
            for sid in hits:
                by_id[sid] = item
        else:
            unmapped.append(item)

    if unmapped:
        # Records without a usable Spotify ID: resolve through ReccoBeats' own id with the /track lookup.
        uuid_map = resolve_uuid_map(batch)
        still_unmapped = 0
        for item in unmapped:
            sid = uuid_map.get(item.get("id"))
            if sid:
                by_id[sid] = item
            else:
                still_unmapped += 1
        if still_unmapped:
            print(f"  warning: {still_unmapped} returned records could not be matched to a Spotify ID")

    if items and not by_id:
        print("  records came back but none could be matched to a Spotify ID, batch skipped. "
              "Run --probe and check the response shape.")
        return None

    rows = []
    for sid in batch:
        item = by_id.get(sid)
        f = parse_features(item)
        if f:
            rows.append((sid, item.get("id"), f["valence"], f["energy"], f["danceability"],
                         f["acousticness"], f["tempo"], f["instrumentalness"], f["liveness"],
                         f["loudness"], f["speechiness"], f["key"], f["mode"], f["isrc"], "found"))
        else:
            rows.append((sid, None, None, None, None, None, None, None, None, None, None,
                         None, None, None, "not_found"))
    return rows


def get_pending_track_ids(conn, limit=None, retry_misses=False, refresh_found=False, source="plays"):
    """Every track that has no stored result, plus stored misses older than the retry window.
    With refresh_found, tracks that already have features are fetched again too (to fill newer columns).
    source: "plays" = tracks played since the pipeline started (raw_recently_played), "history" = tracks in the imported
    streaming history (raw_streaming_history, most played first), "all" = both."""
    stale = "TRUE" if retry_misses else f"f.fetched_at < now() - interval '{RETRY_NOT_FOUND_DAYS} days'"
    refresh = "OR f.status = 'found'" if refresh_found else ""
    wanted = {
        "plays": "SELECT DISTINCT track_id, 0 AS real_plays FROM raw_recently_played",
        "history": "SELECT track_id, count(*) FILTER (WHERE ms_played >= 30000) AS real_plays "
                   "FROM raw_streaming_history GROUP BY track_id",
        "all": "SELECT track_id, max(real_plays) AS real_plays FROM ("
               "SELECT track_id, 0 AS real_plays FROM raw_recently_played UNION ALL "
               "SELECT track_id, count(*) FILTER (WHERE ms_played >= 30000) FROM raw_streaming_history GROUP BY track_id"
               ") u GROUP BY track_id",
    }[source]
    sql = f"""
        SELECT w.track_id
        FROM ({wanted}) w
        LEFT JOIN raw_track_features f ON f.track_id = w.track_id
        WHERE f.track_id IS NULL
           OR (f.status = 'not_found' AND {stale})
           {refresh}
        ORDER BY w.real_plays DESC, w.track_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def save_rows(conn, rows):
    """Upsert. first_fetched_at is never touched on update, so a miss that later turns into a hit
    is visible as status = 'found' AND fetched_at > first_fetched_at."""
    if not rows:
        return
    query = """
        INSERT INTO raw_track_features
            (track_id, reccobeats_id, valence, energy, danceability, acousticness, tempo,
             instrumentalness, liveness, loudness, speechiness, key, mode, isrc, status)
        VALUES %s
        ON CONFLICT (track_id) DO UPDATE SET
            reccobeats_id = EXCLUDED.reccobeats_id,
            valence       = EXCLUDED.valence,
            energy        = EXCLUDED.energy,
            danceability  = EXCLUDED.danceability,
            acousticness  = EXCLUDED.acousticness,
            tempo         = EXCLUDED.tempo,
            instrumentalness = EXCLUDED.instrumentalness,
            liveness      = EXCLUDED.liveness,
            loudness      = EXCLUDED.loudness,
            speechiness   = EXCLUDED.speechiness,
            key           = EXCLUDED.key,
            mode          = EXCLUDED.mode,
            isrc          = EXCLUDED.isrc,
            status        = EXCLUDED.status,
            fetched_at    = now()
    """
    with conn.cursor() as cur:
        execute_values(cur, query, rows)
    conn.commit()


def probe():
    """Try the request formats on the 20 most-played tracks and report what comes back. Writes nothing."""
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT track_id, max(track_name), count(*)
            FROM raw_recently_played
            GROUP BY track_id
            ORDER BY count(*) DESC, max(played_at) DESC
            LIMIT 20
        """)
        tracks = cur.fetchall()
    conn.close()
    ids = [t[0] for t in tracks]
    print(f"Sample: your {len(ids)} most-played tracks, e.g.")
    for tid, name, plays in tracks[:4]:
        print(f"  {tid}  {name} ({plays} plays)")

    tests = [
        ("A. /track lookup, repeated ids  (documented format; CONTROL: does ReccoBeats know these tracks?)",
         "/track", [("ids", i) for i in ids]),
        ("B. /audio-features, repeated ids  (what the script now sends)",
         BATCH_PATH, [("ids", i) for i in ids]),
        ("C. /audio-features, one comma-joined value  (what the first probe sent)",
         BATCH_PATH, {"ids": ",".join(ids)}),
    ]
    for label, path, params in tests:
        print("\n" + "=" * 72)
        print(label)
        resp = http_get(path, params=params)
        if resp is None:
            print("  no response")
            continue
        print(f"  HTTP {resp.status_code}")
        try:
            items = extract_items(resp.json())
        except ValueError:
            items = None
        if items is None:
            print("  shape not recognised:", resp.text[:300])
            continue
        matched = {c for it in items for c in candidate_ids(it) if c in set(ids)}
        print(f"  {len(items)} records, {len(matched)} of {len(ids)} matched to your Spotify IDs by URL")
        if items:
            print("  fields in a record:", sorted(items[0].keys()))
            print("  first record:", json.dumps(items[0])[:500])
        time.sleep(PAUSE_S)


def run(limit=None, retry_misses=False, refresh_found=False, source="plays"):
    conn = get_db_connection()
    pending = get_pending_track_ids(conn, limit, retry_misses, refresh_found, source)
    print(f"{len(pending)} tracks to look up ({BATCH_SIZE} per request)")
    found = not_found = skipped = 0

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        rows = process_batch(batch)
        if rows is None:
            skipped += len(batch)
        else:
            save_rows(conn, rows)
            hits = sum(1 for r in rows if r[-1] == "found")
            found += hits
            not_found += len(rows) - hits
        print(f"  {min(start + BATCH_SIZE, len(pending))}/{len(pending)}  "
              f"found={found} not_found={not_found} skipped={skipped}")
        time.sleep(PAUSE_S)

    conn.close()
    print(f"Done. found={found} not_found={not_found} skipped(will retry)={skipped}")
    return {"found": found, "not_found": not_found, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--retry-misses", action="store_true")
    parser.add_argument("--history", action="store_true",
                        help="look up the tracks of the imported Spotify history (raw_streaming_history), most played first")
    parser.add_argument("--refresh-found", action="store_true",
                        help="also fetch tracks that already have features again (fills newer rating columns)")
    args = parser.parse_args()
    if args.probe:
        probe()
    else:
        run(args.limit, args.retry_misses, args.refresh_found, "history" if args.history else "plays")