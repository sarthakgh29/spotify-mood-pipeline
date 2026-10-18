"""Create a Spotify playlist from a list of track ids (used by the Lifetime Wrapped "Look up" tab).

One-time setup: run `python playlists.py` and approve the extra permission in the browser tab it opens. The
token is kept in .spotify_playlist_cache (git-ignored), separate from the ingest token, so ingest keeps working
with its read-only permission. This module only ever creates new playlists; it never edits or deletes any.
"""
import os
import re
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".spotify_playlist_cache"
SCOPE = "playlist-modify-private playlist-modify-public"
TRACK_ID = re.compile(r"[A-Za-z0-9]{22}")
MAX_ITEMS_PER_CALL = 100       # Spotify's limit for one add-items request
MAX_NAME = 100


class NotAuthorised(Exception):
    """No usable playlist token yet: run `python playlists.py` once."""


def clean_name(name):
    return " ".join((name or "").split())[:MAX_NAME]


def track_uris(track_ids):
    """Unique, valid track ids as Spotify URIs, in the order given."""
    seen, out = set(), []
    for t in track_ids:
        if isinstance(t, str) and TRACK_ID.fullmatch(t) and t not in seen:
            seen.add(t)
            out.append(f"spotify:track:{t}")
    return out


def _auth(open_browser):
    load_dotenv(ROOT / ".env")
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"), client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"), scope=SCOPE, open_browser=open_browser,
        cache_handler=CacheFileHandler(cache_path=str(CACHE)))


def get_client():
    """A Spotify client from the saved token (refreshed if needed). Never opens a browser."""
    auth = _auth(open_browser=False)
    token = auth.validate_token(auth.cache_handler.get_cached_token())
    if not token:
        raise NotAuthorised("Run `python playlists.py` once to approve playlist creation.")
    return spotipy.Spotify(auth=token["access_token"])


def _norm(text):
    return " ".join((text or "").casefold().split())


def _title_core(title):
    """'Satranga (From "ANIMAL")' -> 'satranga'; used to match the same song across releases."""
    return _norm(re.split(r"\s*[(\[]|\s*-(?:\s|$)", title or "", maxsplit=1)[0])


def find_playable_copy(sp, title, artist):
    """Search for a playable copy of a song by title and artist; the id, or None. Returns the best match."""
    want_art, want_title = _norm(artist), _title_core(title)
    for q in (f"track:{title} artist:{artist}", f"{title} {artist}"):   # the plain query helps with odd punctuation
        try:
            items = sp.search(q=q, type="track", limit=10, market="IN")["tracks"]["items"]
        except Exception:
            continue
        for exact in (True, False):
            for it in items:
                if not it or it.get("is_playable") is False:
                    continue
                if want_art not in {_norm(a["name"]) for a in it.get("artists", [])}:
                    continue
                same = _norm(it["name"]) == _norm(title) if exact else _title_core(it["name"]) == want_title
                if same:
                    return it["id"]
    return None


def is_playable(sp, track_id):
    """False for ids Spotify no longer plays (old releases in a downloaded history often are). Unknown counts as playable."""
    try:
        t = sp.track(track_id, market="IN")
    except Exception:
        return True
    return bool(t.get("name")) and t.get("is_playable") is not False


def resolve_playable(sp, tracks):
    """tracks: dicts with track_id, track_name, artist_name. Keep the playable ones, swap dead ids for a playable
    copy found by search. Returns (ids in the same order, names of songs with no playable copy)."""
    ids, missing, seen = [], [], set()
    for t in tracks:
        tid = t["track_id"]
        if not is_playable(sp, tid):
            tid = find_playable_copy(sp, t["track_name"], t["artist_name"])
        if tid is None:
            missing.append(t["track_name"])
        elif tid not in seen:
            seen.add(tid)
            ids.append(tid)
    return ids, missing


def create_playlist(sp, name, track_ids, public=False, description="Made from my listening history"):
    """Create a new playlist with these tracks. Returns {id, url, name, added}."""
    name, uris = clean_name(name), track_uris(track_ids)
    if not name:
        raise ValueError("The playlist needs a name.")
    if not uris:
        raise ValueError("There are no valid tracks to add.")
    # /me/playlists: Spotify's current endpoint (the older /users/{id}/playlists now answers 403)
    pl = sp.current_user_playlist_create(name, public=public, description=description)
    for i in range(0, len(uris), MAX_ITEMS_PER_CALL):
        sp.playlist_add_items(pl["id"], uris[i:i + MAX_ITEMS_PER_CALL])
    return {"id": pl["id"], "url": pl["external_urls"]["spotify"], "name": name, "added": len(uris)}


if __name__ == "__main__":
    auth = _auth(open_browser=True)
    token = auth.get_access_token(as_dict=True)
    me = spotipy.Spotify(auth=token["access_token"]).current_user()
    print(f"Authorised as {me.get('display_name') or me['id']}. Playlist creation is now enabled.")
