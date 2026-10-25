"""One Spotify playlist per mood, built from the whole listening history.

The moods come from ReccoBeats valence and energy (dbt model history_song_moods). The songs of a mood are the ones you played
most. Only new private playlists are created; existing playlists are never edited or deleted.

    python mood_playlists.py --dry-run              # show what each playlist would hold
    python mood_playlists.py --create               # create all four
    python mood_playlists.py --create --mood calm --max 50 --min-plays 3
"""
import argparse
import re
import sys

from ingest_features import get_db_connection
import playlists

MOODS = ["upbeat", "intense", "calm", "mellow"]
DESCRIPTIONS = {
    "upbeat": "Happy and energetic (valence and energy both 0.5 or higher), from my listening history",
    "intense": "Energetic but darker (energy 0.5 or higher, valence below 0.5), from my listening history",
    "calm": "Happy and relaxed (valence 0.5 or higher, energy below 0.5), from my listening history",
    "mellow": "Low energy and low valence (both below 0.5), from my listening history",
}


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def pick_songs(rows, max_songs=100, min_plays=2):
    """rows: dicts with track_id, track_name, artist_name, real_plays. The most played songs with at least min_plays
    real plays, one per title and artist (the same song on an album and a single counts once)."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: (-r["real_plays"], r["track_name"] or "")):
        if r["real_plays"] < min_plays:
            continue
        key = (norm(r["track_name"]), norm(r["artist_name"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= max_songs:
            break
    return out


def playlist_name(mood, today=None):
    return f"{mood.capitalize()} from my history"


def load_rows(conn, mood):
    with conn.cursor() as cur:
        cur.execute("SELECT track_id, track_name, artist_name, real_plays FROM dbt_dev.history_song_moods WHERE audio_mood = %s", (mood,))
        return [dict(zip(("track_id", "track_name", "artist_name", "real_plays"), row)) for row in cur.fetchall()]


def existing(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT mood, name, url, songs, created_at FROM mood_playlists ORDER BY created_at DESC")
        return cur.fetchall()


def record(conn, mood, result):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO mood_playlists (mood, playlist_id, url, name, songs) VALUES (%s, %s, %s, %s, %s)",
                    (mood, result["id"], result["url"], result["name"], result["added"]))
    conn.commit()


def build(conn, moods, max_songs=100, min_plays=2, public=False, create=False, sp=None):
    """Returns one dict per mood: {mood, picked, playlist (when created), missing}."""
    results = []
    for mood in moods:
        picked = pick_songs(load_rows(conn, mood), max_songs, min_plays)
        item = {"mood": mood, "picked": picked, "playlist": None, "missing": []}
        if create and picked:
            ids, missing = playlists.resolve_playable(sp, picked)
            item["missing"] = missing
            if ids:
                item["playlist"] = playlists.create_playlist(sp, playlist_name(mood), ids, public, DESCRIPTIONS[mood])
                record(conn, mood, item["playlist"])
        results.append(item)
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")     # song titles in any script, on a console that cannot show them
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--create", action="store_true", help="create the playlists on Spotify (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true", help="only show what would be created")
    ap.add_argument("--mood", choices=MOODS, action="append", help="only this mood (can repeat)")
    ap.add_argument("--max", type=int, default=100, dest="max_songs", help="songs per playlist (default 100)")
    ap.add_argument("--min-plays", type=int, default=2, help="least real plays for a song to qualify (default 2)")
    ap.add_argument("--public", action="store_true", help="make the playlists public (default private)")
    args = ap.parse_args()
    create = args.create and not args.dry_run
    conn = get_db_connection()
    sp = playlists.get_client() if create else None
    for item in build(conn, args.mood or MOODS, args.max_songs, args.min_plays, args.public, create, sp):
        print(f"\n{item['mood']}: {len(item['picked'])} songs")
        for t in item["picked"][:5]:
            print(f"   {t['track_name']} - {t['artist_name']} ({t['real_plays']} plays)")
        if item["playlist"]:
            print(f"   created: {item['playlist']['url']} ({item['playlist']['added']} added)")
        if item["missing"]:
            print(f"   skipped, no playable copy: {len(item['missing'])}")


if __name__ == "__main__":
    main()
