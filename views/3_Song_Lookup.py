"""Paste a Spotify song link: see its details, ReccoBeats ratings, Last.fm tags and whether the two mood labels agree.
Nothing on this page is saved to the database."""
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text

import covers
import lookup
from db import get_engine
from track_ui import MOOD_COLORS, esc, inject_css, mood_badge, tag_chip

load_dotenv()
inject_css()
MOODS = lookup.MOODS


# ------------------------------------------------------------------ cached lookups
@st.cache_data(show_spinner=False)
def get_seed():
    return lookup.load_genre_mood_map()


@st.cache_data(ttl=3600, show_spinner=False)
def get_track(track_id):
    return lookup.fetch_spotify_track(track_id)


@st.cache_data(ttl=3600, show_spinner=False)
def get_recco(track_id):
    return lookup.fetch_reccobeats(track_id)


@st.cache_data(ttl=3600, show_spinner=False)
def get_lf_artist(name):
    return lookup.lastfm_artist(name)


@st.cache_data(ttl=3600, show_spinner=False)
def get_lf_track(artist, track):
    return lookup.lastfm_track(artist, track)


def play_history(track_id):
    """How often this song is in your own history (None if the database can't be reached)."""
    try:
        query = text("SELECT count(*) AS plays, min(played_at) AS first_play, max(played_at) AS last_play "
                     "FROM dbt_dev.stg_recently_played WHERE track_id = :t")
        return pd.read_sql(query, get_engine(), params={"t": track_id}).iloc[0]
    except Exception:
        return None


def fmt_ms(ms):
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}" if ms else "unknown"


# ------------------------------------------------------------------ page
st.title("🔎 Song lookup")
st.markdown(
    "Paste a Spotify song link. This page asks ReccoBeats for the song's audio ratings and Last.fm for the artist's "
    "tags, then shows the mood each method gives it. Nothing is saved: a looked-up song is not added to your history."
)
link = st.text_input("Spotify song link", placeholder="https://open.spotify.com/track/...")
if not link.strip():
    st.info("In Spotify, open a song, choose Share, then Copy Song Link, and paste it above.")
    st.stop()

track_id = lookup.parse_track_id(link)
if not track_id:
    st.error("That doesn't look like a Spotify song link. It should look like https://open.spotify.com/track/... "
             "(album, artist and playlist links don't work here).")
    st.stop()

try:
    with st.spinner("Asking Spotify..."):
        track = get_track(track_id)
except lookup.LookupFailed as exc:
    st.error(str(exc))
    st.stop()

# ---------------------------------------------------------------- the song
c_img, c_info = st.columns([1, 3])
with c_img:
    if track["image"] and covers.is_allowed_cover_url(track["image"]):
        st.image(track["image"], width=200)
with c_info:
    st.subheader(track["name"])
    st.markdown(f"**{', '.join(a['name'] for a in track['artists'])}**")
    st.caption(" | ".join(str(b) for b in (track["album"], track["release_date"], fmt_ms(track["duration_ms"])) if b))
    if track["isrc"]:
        st.caption(f"ISRC {track['isrc']}")
    st.link_button("Open in Spotify", track["url"])
    history = play_history(track_id)
    if history is not None and int(history["plays"]) > 0:
        first = pd.Timestamp(history["first_play"]).tz_convert("Asia/Kolkata").strftime("%d %b")
        last = pd.Timestamp(history["last_play"]).tz_convert("Asia/Kolkata").strftime("%d %b")
        st.success(f"In your history: played {int(history['plays'])} time(s), first {first}, last {last}.")

# ---------------------------------------------------------------- ReccoBeats
st.divider()
st.subheader("ReccoBeats")
recco, recco_error = None, None
try:
    with st.spinner("Asking ReccoBeats..."):
        recco = get_recco(track_id)
except lookup.LookupFailed as exc:
    recco_error = str(exc)

audio = None
if recco_error:
    st.warning(recco_error)
elif recco is None:
    year = (track["release_date"] or "")[:4]
    note = ""
    if year.isdigit() and int(year) >= 2025:
        note = (f" It was released in {year}; in your own listening, ReccoBeats knew far fewer "
                "recent releases than older ones.")
    st.info("ReccoBeats doesn't have this song, so there are no audio ratings." + note)
else:
    rows = [{"Rating": label, "Value": recco.get(key), "What it means": meaning}
            for key, label, meaning in lookup.FEATURES if recco.get(key) is not None]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Value": st.column_config.NumberColumn("Value", format="%.3f")})
    valence, energy = recco.get("valence"), recco.get("energy")
    audio = lookup.audio_mood(valence, energy)
    if audio:
        st.markdown(f"**Audio mood:** {mood_badge(audio)}", unsafe_allow_html=True)
        st.latex(r"v=%.3f,\ e=%.3f\ \Rightarrow\ \text{%s}" % (valence, energy, audio))
        st.caption("Valence at or above 0.5 is positive and energy at or above 0.5 is energetic; "
                   "the four combinations are upbeat, intense, calm and mellow. These are ReccoBeats' estimates, not Spotify's.")

# ---------------------------------------------------------------- Last.fm
st.divider()
st.subheader("Last.fm")
seed = get_seed()
st.caption("Last.fm tags artists, not songs. The genre mood is a vote among the artist's top tags (at most five, "
           f"each with a weight of at least {lookup.MIN_TAG_WEIGHT}), using the seed list. "
           "The pipeline uses the **first-listed artist**.")

genre = None
primary = track["artists"][0]["name"] if track["artists"] else None
results = {}
for i, artist in enumerate(track["artists"]):
    name = artist["name"]
    try:
        with st.spinner(f"Asking Last.fm about {name}..."):
            info = get_lf_artist(name)
    except lookup.LookupFailed as exc:
        st.warning(f"{name}: {exc}")
        continue
    result = lookup.vote(info["tags"], seed)
    results[name] = (info, result)
    if i == 0:
        genre = result["winner"]
    title = name + ("  (first-listed artist, used for the genre mood)" if i == 0 else "")
    with st.expander(title, expanded=(i == 0)):
        if not info["found"]:
            st.info("Last.fm has no data for this artist.")
            continue
        m1, m2 = st.columns(2)
        m1.metric("Listeners", f"{info['listeners']:,}" if info["listeners"] else "n/a")
        m2.metric("Scrobbles", f"{info['playcount']:,}" if info["playcount"] else "n/a")
        if info["tags"]:
            tag_df = pd.DataFrame({
                "Tag": [t["tag"] for t in result["per_tag"]],
                "Weight": [t["weight"] for t in result["per_tag"]],
                "Used in the vote": ["yes" if t["used"] else "no" for t in result["per_tag"]],
                "Mood from the seed list": [t["mood"] or ("none (ignored)" if t["used"] else "") for t in result["per_tag"]],
            })
            st.dataframe(tag_df, hide_index=True, width="stretch", column_config={
                "Weight": st.column_config.ProgressColumn("Weight", min_value=0, max_value=100, format="%d")})
            chips = "".join(tag_chip(t["tag"], t["mood"]) for t in result["per_tag"] if t["used"])
            votes = " &middot; ".join(f"{m} {result['counts'][m]}" for m in MOODS)
            st.markdown(f"**Votes:** {votes}<br>{chips}<br>**Genre mood:** {mood_badge(result['winner'])} "
                        f"<span class='muted'>({esc(result['how'])})</span>", unsafe_allow_html=True)
        else:
            st.info("Last.fm has no tags for this artist, so there is no genre mood.")
        if info["similar"]:
            st.markdown("**Similar artists:** " + ", ".join(esc(s) for s in info["similar"]), unsafe_allow_html=True)

if primary:
    try:
        song_lf = get_lf_track(primary, track["name"])
    except lookup.LookupFailed as exc:
        song_lf = None
        st.warning(f"Song-level data: {exc}")
    if song_lf is not None:
        with st.expander("Song-level data from Last.fm"):
            if not song_lf["found"]:
                st.info("Last.fm has nothing about this exact song.")
            else:
                s1, s2 = st.columns(2)
                s1.metric("Song listeners", f"{song_lf['listeners']:,}" if song_lf["listeners"] else "n/a")
                s2.metric("Song scrobbles", f"{song_lf['playcount']:,}" if song_lf["playcount"] else "n/a")
                if song_lf["tags"]:
                    st.dataframe(pd.DataFrame(song_lf["tags"], columns=["Tag", "Weight"]), hide_index=True, width="stretch")
                else:
                    st.caption("No song-level tags. For most songs in your history Last.fm has none, "
                               "so the artist's tags are used.")

# ---------------------------------------------------------------- compare
st.divider()
st.subheader("Do the two methods agree?")
b1, b2, b3 = st.columns(3)
b1.markdown("**Last.fm genre mood**")
b1.markdown(mood_badge(genre), unsafe_allow_html=True)
b2.markdown("**ReccoBeats audio mood**")
b2.markdown(mood_badge(audio), unsafe_allow_html=True)
b3.markdown("**Result**")
if genre and audio:
    b3.markdown('<span style="color:#1DB954;font-weight:600">Same label</span>' if genre == audio
                else '<span style="color:#FFC000;font-weight:600">Different labels</span>', unsafe_allow_html=True)
else:
    b3.markdown('<span class="muted">needs both labels</span>', unsafe_allow_html=True)

if recco and audio:
    point = pd.DataFrame({"valence": [recco["valence"]], "energy": [recco["energy"]], "song": [track["name"]],
                          "Last.fm genre mood": [genre or "none"]})
    fig = px.scatter(point, x="valence", y="energy", color="Last.fm genre mood", hover_name="song",
                     color_discrete_map={**MOOD_COLORS, "none": "#8a919c"}, range_x=[0, 1], range_y=[0, 1],
                     labels={"valence": "Valence (positivity)", "energy": "Energy"})
    fig.add_vline(x=0.5, line_dash="dot", opacity=0.5)
    fig.add_hline(y=0.5, line_dash="dot", opacity=0.5)
    for x, y, label in ((0.75, 0.97, "upbeat"), (0.25, 0.97, "intense"), (0.75, 0.03, "calm"), (0.25, 0.03, "mellow")):
        fig.add_annotation(x=x, y=y, text=f"audio: {label}", showarrow=False, opacity=0.55)
    fig.update_traces(marker=dict(size=16))
    fig.update_layout(height=380, margin=dict(t=10, b=10), legend=dict(orientation="h", y=-0.25, title_text=""))
    st.plotly_chart(fig, width="stretch")
    st.caption("Where this song sits on ReccoBeats' valence and energy scale. The dot's colour is the Last.fm label.")

with st.expander("All the raw data"):
    st.json({
        "spotify": track,
        "reccobeats": recco,
        "lastfm_artists": {n: {"info": i, "vote": v} for n, (i, v) in results.items()},
    }, expanded=False)
