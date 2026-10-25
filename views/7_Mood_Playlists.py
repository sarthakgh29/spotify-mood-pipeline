"""Mood Playlists: pick a mood, choose how many songs, untick the ones you do not want, name it, and add it to Spotify."""
import random
import webbrowser

import pandas as pd
import streamlit as st

import mood_playlists as mp
import playlists
from db import get_engine
from track_ui import COVER_COLUMN, add_cover_column

POOL = 300          # most songs one playlist can hold on this page
MOOD_TEXT = {
    "upbeat": "Happy and energetic",
    "intense": "Energetic but darker",
    "calm": "Happy and relaxed",
    "mellow": "Low energy, low valence",
}

st.title("Mood Playlists")
st.caption("Songs from your whole listening history, sorted into four moods by ReccoBeats valence and energy. "
           "Pick a mood, choose how many songs, untick any you do not want, name it, and add it to Spotify.")


@st.cache_data(ttl=300, show_spinner=False)
def mood_pool(mood):
    """Every song of the mood played at least twice, most played first."""
    return mp.pick_songs(mp.load_rows(get_engine().raw_connection(), mood), 10 ** 6, min_plays=2)


@st.cache_data(ttl=60, show_spinner=False)
def made_playlists():
    return pd.read_sql("SELECT mood, name, url, songs, created_at FROM mood_playlists ORDER BY created_at DESC", get_engine())


tabs = st.tabs([m.capitalize() for m in mp.MOODS])
for tab, mood in zip(tabs, mp.MOODS):
    with tab:
        pool = pd.DataFrame(mood_pool(mood))
        if pool.empty:
            st.info("No songs for this mood yet. Run `python ingest_features.py --history`, then `dbt build`.")
            continue
        st.caption(f"{MOOD_TEXT[mood]}. {len(pool):,} songs played at least twice.")
        n = st.slider("How many songs", 1, min(POOL, len(pool)), min(50, len(pool)), key=f"n_{mood}")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Randomize", key=f"rand_{mood}", help="Pick a different set from all the songs of this mood"):
            st.session_state[f"seed_{mood}"] = random.randrange(1 << 30)
        if b2.button("Most played", key=f"top_{mood}", help="Back to your most played songs"):
            st.session_state[f"seed_{mood}"] = None
        seed = st.session_state.get(f"seed_{mood}")
        shown = pool.head(n) if seed is None else pool.sample(n=n, random_state=seed).sort_values("real_plays", ascending=False)
        st.caption("Showing your most played songs." if seed is None else "Showing a random pick, most played first. Click Randomize again for another.")
        table = add_cover_column(pd.DataFrame({
            "Add": True, "Song": shown["track_name"].values, "Artist": shown["artist_name"].values,
            "Plays": shown["real_plays"].values}), shown["track_id"])
        st.caption("Untick the songs you do not want in the playlist.")
        edited = st.data_editor(
            table, hide_index=True, width="stretch", height=420, key=f"ed_{mood}_{n}_{seed}",
            column_config={"Cover": COVER_COLUMN, "Add": st.column_config.CheckboxColumn("Add", width="small")},
            disabled=["Cover", "Song", "Artist", "Plays"])
        chosen = shown[edited["Add"].values]

        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Playlist name", value=mp.playlist_name(mood), key=f"name_{mood}", max_chars=playlists.MAX_NAME)
        public = c2.checkbox("Public", value=False, key=f"pub_{mood}")
        st.caption(f"Will create a {'public' if public else 'private'} playlist called \"{playlists.clean_name(name)}\" "
                   f"with {len(chosen)} songs. It is added to your Spotify account; nothing existing is changed.")
        if st.button("Add to Spotify", key=f"go_{mood}", type="primary", disabled=chosen.empty):
            try:
                sp = playlists.get_client()
                with st.spinner("Checking each song is still playable on Spotify..."):
                    ids, missing = playlists.resolve_playable(sp, chosen.to_dict("records"))
                res = playlists.create_playlist(sp, name, ids, public=public, description=mp.DESCRIPTIONS[mood])
                mp.record(get_engine().raw_connection(), mood, res)
                made_playlists.clear()
                webbrowser.open_new_tab(res["url"])     # the dashboard runs on this machine, so this opens a tab for you
                st.success(f"Created \"{res['name']}\" with {res['added']} songs.")
                if missing:
                    st.info("Left out because Spotify has no playable copy: " + ", ".join(missing))
                st.link_button("Open it in Spotify again", res["url"])
            except playlists.NotAuthorised:
                st.warning("One-time setup needed: run `python playlists.py` in the project folder, approve the "
                           "permission in the browser tab that opens, then click again.")
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Spotify did not accept that ({exc.__class__.__name__}). Nothing was created, or it may "
                         "be partly created: check your Spotify playlists.")

made = made_playlists()
if not made.empty:
    st.subheader("Playlists you made here")
    st.dataframe(made.rename(columns={"mood": "Mood", "name": "Name", "url": "Link", "songs": "Songs", "created_at": "Made"}),
                 hide_index=True, width="stretch", column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")})
