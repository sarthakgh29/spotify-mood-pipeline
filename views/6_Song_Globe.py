"""Song Globe: your songs on a spinnable globe, placed by who they were played with.

The map comes from globe_data.py (sessions -> embedding -> t-SNE); the globe that draws it is Johan Chopra's, from his
Lifetime-Wrapped project (see globe_assets/globe.js). Covers come from track_covers (python globe_covers.py fills them in)."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import globe_data
import wrapped as w
from db import get_engine

ASSETS = Path(__file__).resolve().parent.parent / "globe_assets"
TOP_FOR_COVERS = 2000          # the globe uses songs that have a cover; this many most played ones are looked up
MIN_COVERS = 150               # fewer songs with covers than this, and the globe shows name tiles instead

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>__CSS__</style></head><body>
<div id="root"></div>
<script>const SPACE = __SPACE__, COVERS = __COVERS__, OPTS = __OPTS__;</script>
<script>__JS__</script>
<script>mountGlobe(document.getElementById("root"), SPACE, { useCovers: OPTS.useCovers, coverUrl: id => COVERS[id], coverTarget: OPTS.target });</script>
</body></html>"""


def as_js(obj):
    """JSON that is safe inside a <script> block."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


@st.cache_resource(ttl=3600, show_spinner="Loading your listening history...")
def load_history():
    df = pd.read_sql(
        "select played_at, track_id, track_name, artist_name, album_name, seconds_played::float as seconds_played, "
        "is_real_play, skipped from dbt_dev.all_plays", get_engine())
    return w.prepare(df)


@st.cache_data(ttl=600, show_spinner=False)
def load_cover_urls():
    c = pd.read_sql("select track_id, cover_url from track_covers where cover_url is not null", get_engine())
    return dict(zip(c["track_id"], c["cover_url"]))


@st.cache_data(show_spinner="Mapping your songs by who they were played with (a few seconds)...")
def song_space(sig):
    return globe_data.build_song_space(w.real_plays(load_history()))


@st.cache_data(show_spinner=False)
def cover_map(sig, urls_version):
    """{id of a song's most played release: cover url}, trying the song's other releases too."""
    real = w.real_plays(load_history())
    urls = load_cover_urls()
    songs = w._songs(real)
    ids = real.groupby("song_key")["track_id"].unique()
    out = {}
    for row in songs.itertuples():
        for tid in [row.track_id, *ids[row.song_key]]:
            if tid in urls:
                out[row.track_id] = urls[tid]
                break
    return out


st.title("Song Globe")
st.caption("Your songs on a globe. Songs you played in the same sittings sit close together, so moving across the globe takes you "
           "from one corner of your taste to the next. The globe is from Johan's Lifetime-Wrapped project.")

try:
    d = load_history()
except Exception as exc:
    st.error(f"Could not load the listening history. Is Docker running, and have `import_history.py` and `dbt build` been run? ({exc.__class__.__name__})")
    st.stop()
if d.empty:
    st.info("No plays yet. Run `python import_history.py Spotify_Extended`, then `dbt build`.")
    st.stop()

sig = (len(d), str(d["played_at"].max()))
space = song_space(sig)
if not space["songs"]:
    st.info("There is not enough listening history to map yet (it needs at least 60 different songs played in 10 or more sittings).")
    st.stop()

urls = load_cover_urls()
covers = cover_map(sig, len(urls))
songs = space["songs"]
top = songs[:TOP_FOR_COVERS]
have = sum(1 for s in top if s["id"] in covers)
use_covers = len(covers) >= MIN_COVERS

if use_covers:
    st.caption(f"{have:,} of your {len(top):,} most played songs have a cover and can appear on the globe."
               + (" Run `python globe_covers.py` to fetch the missing ones." if have < len(top) * 0.95 else ""))
else:
    st.info("Fewer than 150 songs have a cover yet, so the globe shows name tiles. Run `python globe_covers.py` to fetch covers.")

html = (PAGE.replace("__CSS__", (ASSETS / "globe.css").read_text(encoding="utf-8"))
            .replace("__JS__", (ASSETS / "globe.js").read_text(encoding="utf-8"))
            .replace("__SPACE__", as_js(space))
            .replace("__COVERS__", as_js(covers))
            .replace("__OPTS__", as_js({"useCovers": use_covers, "target": min(TOP_FOR_COVERS, len(songs))})))
components.html(html, height=900, scrolling=True)
