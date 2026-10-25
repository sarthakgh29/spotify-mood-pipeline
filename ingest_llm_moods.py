"""Label every track's mood with Gemini and store the answers in raw_llm_moods.

Usage:
    python ingest_llm_moods.py --dry-run                 show what would be sent for 3 tracks; no API call, nothing stored
    python ingest_llm_moods.py --only-labelled --limit 5 try it on a few of the tracks you hand-labelled first
    python ingest_llm_moods.py                           label every track not yet labelled (both variants)
    python ingest_llm_moods.py --variant text_only       only the variant that doesn't see the ReccoBeats numbers
    python ingest_llm_moods.py --variant with_notes      only songs you described in the Mood Lab, using your description

Needs GEMINI_API_KEY in .env. Only song metadata is sent (title, artist names, album, Last.fm tags and, for the
hybrid and with_notes variants, ReccoBeats' numbers; for with_notes also your own description of the song): never ids,
dates, keys or play history. The with_notes variant sees your words, so it is not a fair test against your own labels. A label is stored once per
(track, model, prompt version), so re-running only pays for tracks that are still missing one.
"""
import argparse
import time

import ai_labeler as ai
from ingest_features import get_db_connection

TRACK_SQL = """
    SELECT t.track_id, t.track_name, t.artist_names, t.album_name, g.genres AS tags,
           f.valence, f.energy, f.danceability, f.acousticness, f.speechiness, f.loudness, f.tempo,
           l.note
    FROM (SELECT track_id, max(track_name) AS track_name, max(artist_names) AS artist_names,
                 max(album_name) AS album_name, max(primary_artist_id) AS primary_artist_id
          FROM raw_recently_played GROUP BY track_id) t
    LEFT JOIN raw_artist_genres g ON g.artist_id = t.primary_artist_id
    LEFT JOIN raw_track_features f ON f.track_id = t.track_id AND f.status = 'found'
    LEFT JOIN mood_labels l ON l.track_id = t.track_id
    {where}
    ORDER BY t.track_id
"""


def load_tracks(conn, only_labelled=False):
    where = "WHERE t.track_id IN (SELECT track_id FROM mood_labels)" if only_labelled else ""
    with conn.cursor() as cur:
        cur.execute(TRACK_SQL.format(where=where))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def variant_tracks(tracks, variant):
    """The with_notes variant only applies to songs the listener has described."""
    if variant == "with_notes":
        return [t for t in tracks if ai.clean_note(t.get("note"))]
    return tracks


def labelled_ids(conn, model, prompt_version):
    with conn.cursor() as cur:
        cur.execute("SELECT track_id FROM raw_llm_moods WHERE model = %s AND prompt_version = %s",
                    (model, prompt_version))
        return {r[0] for r in cur.fetchall()}


def save_label(conn, track_id, model, prompt_version, answer):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_llm_moods (track_id, model, prompt_version, mood, confidence, reason)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (track_id, model, prompt_version) DO UPDATE SET
                   mood = EXCLUDED.mood, confidence = EXCLUDED.confidence,
                   reason = EXCLUDED.reason, labelled_at = now()""",
            (track_id, model, prompt_version, answer.mood, answer.confidence, answer.reason),
        )
    conn.commit()


def run(variants, limit=None, only_labelled=False, dry_run=False, pause=2.0):
    conn = get_db_connection()
    try:
        tracks = load_tracks(conn, only_labelled)
        model = ai.configured_model()
        print(f"{len(tracks)} tracks{' (hand-labelled only)' if only_labelled else ''}; model {model}")

        if dry_run:
            for variant in variants:
                pending = ai.select_pending(variant_tracks(tracks, variant),
                                            labelled_ids(conn, model, ai.VARIANTS[variant]), limit)
                print(f"\n[{variant}] {len(pending)} tracks would be labelled. First prompts that would be sent:")
                for track in pending[:3]:
                    print("-" * 60)
                    print(ai.build_prompt(track, variant))
            print("\nDry run: no API call was made and nothing was stored.")
            return

        call = ai.GeminiLabeler()
        model = call.model
        for variant in variants:
            version = ai.VARIANTS[variant]
            pending = ai.select_pending(variant_tracks(tracks, variant), labelled_ids(conn, model, version), limit)
            print(f"\n[{variant}] {len(pending)} tracks to label")
            done = skipped = 0
            for i, track in enumerate(pending, 1):
                answer = ai.label_track(track, variant, call)
                if answer is None:
                    skipped += 1
                else:
                    save_label(conn, track["track_id"], model, version, answer)
                    done += 1
                if i % 10 == 0 or i == len(pending):
                    print(f"  {i}/{len(pending)}  labelled={done} unusable-answers={skipped}")
                time.sleep(pause)
            print(f"[{variant}] done: {done} stored, {skipped} skipped (will be retried next run)")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=[*ai.VARIANTS, "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="at most this many tracks per variant")
    parser.add_argument("--only-labelled", action="store_true", help="only tracks you have hand-labelled")
    parser.add_argument("--dry-run", action="store_true", help="print prompts, call nothing, store nothing")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between calls (default 2)")
    args = parser.parse_args()
    chosen = list(ai.VARIANTS) if args.variant == "all" else [args.variant]
    try:
        run(chosen, args.limit, args.only_labelled, args.dry_run, args.pause)
    except ai.LabelError as exc:
        raise SystemExit(f"Stopped: {exc}")
