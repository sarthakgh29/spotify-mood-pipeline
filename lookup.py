"""Logic behind the Song Lookup page. Nothing here touches the database or imports Streamlit.

Three sources are combined for one pasted Spotify track:
  * Spotify's public track data (client-credentials login, so no personal sign-in is needed)
  * ReccoBeats audio features  (track-level: valence, energy, ...)
  * Last.fm tags               (artist-level, mapped to a mood with the same seed the pipeline uses)

The only user input is a Spotify link, from which a 22-character track ID is extracted. Every URL that is
fetched is built from a fixed host plus that ID or an artist/track name taken from Spotify, never from the input.
"""
import csv
import os
import re

import requests

import covers
import ingest_features as rb

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(ROOT, "spotify_dbt", "seeds", "genre_mood_map.csv")
LASTFM_URL = "http://ws.audioscrobbler.com/2.0/"

MOODS = ["calm", "mellow", "intense", "upbeat"]
# Same filtering as ingest.fetch_lastfm_tags: tags need a weight of at least 10, at most the top 5 are kept.
MIN_TAG_WEIGHT = 10
MAX_TAGS = 5
ENERGY_THRESHOLD = 0.5
VALENCE_THRESHOLD = 0.5

# (key, label, plain-language meaning). ReccoBeats uses Spotify's former audio-feature names.
FEATURES = [
    ("valence", "Valence", "Musical positivity: low sounds sad or angry, high sounds happy"),
    ("energy", "Energy", "Intensity and activity: fast, loud, noisy tracks score high"),
    ("danceability", "Danceability", "How suitable the song is for dancing"),
    ("acousticness", "Acousticness", "Confidence that the song is acoustic"),
    ("speechiness", "Speechiness", "How much of the song is spoken words (rap scores above singing)"),
    ("instrumentalness", "Instrumentalness", "Likelihood that there are no vocals"),
    ("liveness", "Liveness", "Likelihood of a live audience in the recording"),
    ("loudness", "Loudness (dB)", "Average loudness, negative; closer to 0 is louder"),
    ("tempo", "Tempo (BPM)", "Beats per minute"),
    ("key", "Key", "Pitch class: 0 = C, 1 = C sharp, and so on"),
    ("mode", "Mode", "1 = major, 0 = minor"),
]

_TRACK_URL = re.compile(r"(?:open\.spotify\.com/(?:intl-[A-Za-z-]+/)?track/|spotify:track:)([A-Za-z0-9]{22})")
_BARE_ID = re.compile(r"[A-Za-z0-9]{22}")


class LookupFailed(Exception):
    """A lookup failed in a way worth showing to the user."""


def parse_track_id(text):
    """Spotify track ID from a link, a spotify:track: URI or a bare ID; None if it isn't one."""
    text = (text or "").strip()
    match = _TRACK_URL.search(text)
    if match:
        return match.group(1)
    return text if _BARE_ID.fullmatch(text) else None


def audio_mood(valence, energy, valence_threshold=VALENCE_THRESHOLD, energy_threshold=ENERGY_THRESHOLD):
    """Same rule as the dbt audio_mood macro."""
    if valence is None or energy is None:
        return None
    if energy >= energy_threshold:
        return "upbeat" if valence >= valence_threshold else "intense"
    return "calm" if valence >= valence_threshold else "mellow"


def load_genre_mood_map(path=SEED_PATH):
    """{lower-cased genre tag: mood} from the dbt seed."""
    with open(path, newline="", encoding="utf-8") as f:
        return {row["genre"].strip().lower(): row["mood"].strip() for row in csv.DictReader(f)}


def vote(tags, seed):
    """The pipeline's genre-mood rule, applied to [(tag, weight)] and shown step by step.

    The top five tags with weight >= 10 are 'used'; each used tag votes for the mood the seed gives it
    (case-insensitive, 'unclassified' never votes); the mood with the most votes wins and ties go to the
    alphabetically first mood. Returns the votes per mood, one record per tag, the winner and how decisive it was.
    """
    counts = {m: 0 for m in MOODS}
    per_tag = []
    n_used = 0
    for name, weight in tags:
        is_used = weight >= MIN_TAG_WEIGHT and n_used < MAX_TAGS  # decided by position, in Last.fm's order
        n_used += is_used
        mood = seed.get(name.lower()) if is_used else None
        if mood == "unclassified" or mood not in counts:
            mood = None
        per_tag.append({"tag": name, "weight": weight, "used": is_used, "mood": mood})
        if mood:
            counts[mood] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top, second = ranked[0][1], ranked[1][1]
    total = sum(counts.values())
    if total == 0:
        how = "no tag maps to a mood"
    elif total == 1:
        how = "one tag decided it"
    elif top == second:
        how = "tie, broken alphabetically"
    else:
        how = "clear majority"
    return {"counts": counts, "per_tag": per_tag, "winner": ranked[0][0] if top else None,
            "top": top, "second": second, "how": how}


# ------------------------------------------------------------------ Spotify
def build_spotify_client():
    """Spotify client that needs no user login (public song details only); the token stays in memory."""
    import spotipy
    from spotipy.cache_handler import MemoryCacheHandler
    from spotipy.oauth2 import SpotifyClientCredentials

    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIPY_CLIENT_ID"), client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
            cache_handler=MemoryCacheHandler()),
        requests_timeout=15, retries=1)


def fetch_spotify_track(track_id, client=None):
    client = client or build_spotify_client()
    try:
        t = client.track(track_id)
    except Exception as exc:
        if getattr(exc, "http_status", None) == 404:
            raise LookupFailed("Spotify could not find that song.") from exc
        raise LookupFailed(f"Spotify did not return the song details ({exc.__class__.__name__}).") from exc
    album = t.get("album") or {}
    return {
        "id": t["id"],
        "name": t["name"],
        "artists": [{"id": a.get("id"), "name": a["name"]} for a in t.get("artists", [])],
        "album": album.get("name"),
        "release_date": album.get("release_date"),
        "duration_ms": t.get("duration_ms"),
        "isrc": (t.get("external_ids") or {}).get("isrc"),
        "explicit": t.get("explicit"),
        "image": covers.pick_cover(album.get("images")),
        "url": f"https://open.spotify.com/track/{t['id']}",
    }


# ------------------------------------------------------------------ ReccoBeats
def fetch_reccobeats(track_id):
    """ReccoBeats' full record for the track (all ratings plus ids), or None if it doesn't know the song."""
    resp = rb.http_get(rb.BATCH_PATH, params=rb.batch_params([track_id]))
    if resp is None:
        raise LookupFailed("Could not reach ReccoBeats.")
    if resp.status_code != 200:
        raise LookupFailed(f"ReccoBeats returned HTTP {resp.status_code}.")
    try:
        items = rb.extract_items(resp.json())
    except ValueError:
        raise LookupFailed("ReccoBeats returned something unreadable.")
    for item in items or []:
        if track_id in rb.candidate_ids(item):
            return item
    return None


# ------------------------------------------------------------------ Last.fm
def _lastfm(method, api_key, **params):
    if not api_key:
        raise LookupFailed("No Last.fm API key is configured (LASTFM_API_KEY in .env).")
    try:
        resp = requests.get(LASTFM_URL, params={"method": method, "api_key": api_key, "format": "json", **params},
                            timeout=15)
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise LookupFailed(f"Could not reach Last.fm ({exc.__class__.__name__}).") from exc
    # Last.fm answers "not found" with an {"error": ...} body; treat that as no data, not a failure.
    return {} if "error" in payload else payload


def _tag_list(payload):
    tags = (payload.get("toptags") or {}).get("tag") or []
    return [(t["name"], int(t.get("count", 0))) for t in tags if isinstance(t, dict) and "name" in t]


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def lastfm_artist(name, api_key=None):
    """Tags (with weights), listener and scrobble counts and similar artists for an artist."""
    api_key = api_key or os.getenv("LASTFM_API_KEY")
    tags = _tag_list(_lastfm("artist.gettoptags", api_key, artist=name, autocorrect=1))
    info = _lastfm("artist.getinfo", api_key, artist=name, autocorrect=1).get("artist") or {}
    stats = info.get("stats") or {}
    similar = ((info.get("similar") or {}).get("artist")) or []
    return {
        "name": info.get("name") or name,
        "tags": tags,
        "listeners": _int_or_none(stats.get("listeners")),
        "playcount": _int_or_none(stats.get("playcount")),
        "similar": [s["name"] for s in similar if isinstance(s, dict) and "name" in s][:6],
        "found": bool(info) or bool(tags),
    }


def lastfm_track(artist, track, api_key=None):
    """Song-level tags (with weights) and listener counts; most songs have none."""
    api_key = api_key or os.getenv("LASTFM_API_KEY")
    tags = _tag_list(_lastfm("track.gettoptags", api_key, artist=artist, track=track, autocorrect=1))
    info = _lastfm("track.getinfo", api_key, artist=artist, track=track, autocorrect=1).get("track") or {}
    return {
        "tags": tags,
        "listeners": _int_or_none(info.get("listeners")),
        "playcount": _int_or_none(info.get("playcount")),
        "found": bool(info) or bool(tags),
    }
