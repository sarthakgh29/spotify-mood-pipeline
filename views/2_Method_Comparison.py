import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from db import get_engine
import lookup
from mood_stats import cohen_kappa
from track_ui import (COVER_COLUMN, MOOD_COLORS as TRACK_MOOD_COLORS, add_cover_column, esc, inject_css, mood_badge, tag_chip,
                      track_table)

inject_css()

MOODS = ["calm", "mellow", "intense", "upbeat"]
MOOD_LABELS = [m.capitalize() for m in MOODS]
MOOD_COLORS = {
    "Calm": "#5B9BD5",
    "Mellow": "#1DB954",
    "Intense": "#E33A3A",
    "Upbeat": "#FFC000",
    "No genre label": "#8a8a8a",
}
# Keep in sync with the dbt vars energy_threshold / valence_threshold (defaults 0.5 each)
ENERGY_THRESHOLD = 0.5
VALENCE_THRESHOLD = 0.5


@st.cache_data(ttl=300)
def load_data():
    engine = get_engine()
    plays = pd.read_sql("SELECT * FROM dbt_dev.play_mood_comparison ORDER BY played_at", engine)
    fetch_status = pd.read_sql(
        "SELECT status, count(*) AS tracks FROM raw_track_features GROUP BY status", engine
    )
    total_tracks = pd.read_sql("SELECT count(DISTINCT track_id) AS n FROM raw_recently_played", engine)
    meta = pd.read_sql("""
        SELECT s.track_id, max(s.album_name) AS album_name, max(c.cover_url) AS cover_url,
               max(array_to_string(g.genres, ', ')) AS lastfm_tags
        FROM dbt_dev.stg_recently_played s
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = s.track_id
        LEFT JOIN raw_artist_genres g ON g.artist_id = s.primary_artist_id
        GROUP BY s.track_id
    """, engine)
    ratings = pd.read_sql("""
        SELECT f.track_id, s.track_name, s.artist_names, f.valence, f.energy, f.danceability, f.acousticness,
               f.instrumentalness, f.liveness, f.speechiness, f.loudness, f.tempo
        FROM raw_track_features f
        JOIN (SELECT track_id, max(track_name) AS track_name, max(artist_names) AS artist_names
              FROM dbt_dev.stg_recently_played GROUP BY track_id) s ON s.track_id = f.track_id
        WHERE f.status = 'found'
        ORDER BY s.track_name
    """, engine)
    artist_tags = pd.read_sql("""
        SELECT a.artist_id, a.artist_name, a.genre_mood, a.audio_mood, a.tracks, g.genres
        FROM dbt_dev.mood_comparison_artist a
        JOIN raw_artist_genres g ON g.artist_id = a.artist_id
        ORDER BY a.artist_name
    """, engine)
    return plays, fetch_status, int(total_tracks.iloc[0]["n"]), meta, ratings, artist_tags


st.title("Mood method comparison")
st.caption(
    "Genre method: the artist's Last.fm tags mapped to a mood. "
    f"Audio method: the track's own valence and energy from ReccoBeats, split at energy {ENERGY_THRESHOLD} "
    f"and valence {VALENCE_THRESHOLD}. Neither is ground truth, so the interesting part is where they disagree."
)

try:
    plays, fetch_status, total_tracks, track_meta, ratings, artist_tags = load_data()
except Exception as exc:
    st.error(
        "Could not load the comparison data. Check that raw_track_features exists, "
        "ingest_features.py has run, and dbt has built play_mood_comparison."
    )
    st.code(str(exc))
    st.stop()

if plays.empty:
    st.info("No plays found in dbt_dev.play_mood_comparison yet. Fetch features, then run dbt.")
    st.stop()

plays = plays.copy()
# timestamptz arrives as UTC: convert to IST first so the day boundary is the IST one, then drop the tz
plays["listen_date"] = pd.to_datetime(plays["listen_date"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
plays["day"] = plays["listen_date"].dt.normalize()
plays["duration_minutes"] = pd.to_numeric(plays["duration_minutes"], errors="coerce").astype(float)
plays["valence"] = pd.to_numeric(plays["valence"], errors="coerce")
plays["energy"] = pd.to_numeric(plays["energy"], errors="coerce")

window = st.radio("Window", ["All time", "Last 14 days", "Last 7 days"], horizontal=True)
if window != "All time":
    n_days = 14 if "14" in window else 7
    cutoff = plays["day"].max() - pd.Timedelta(days=n_days - 1)
    plays = plays[plays["day"] >= cutoff]
if plays.empty:
    st.info("No plays in this window.")
    st.stop()

has_genre = plays["genre_mood"].notna().any()
has_audio = plays["audio_mood"].notna().any()
if not has_audio:
    st.warning("No audio features are available for these plays yet. Run ingest_features.py, then dbt.")

# ---------------------------------------------------------------- Coverage
st.subheader("Coverage")
total_min = plays["duration_minutes"].sum()
has_g = plays["genre_mood"].notna()
has_a = plays["audio_mood"].notna()


def pct(minutes):
    return f"{100 * minutes / total_min:.1f}%" if total_min else "0.0%"


c1, c2, c3, c4 = st.columns(4)
c1.metric("Minutes with a genre mood", pct(plays.loc[has_g, "duration_minutes"].sum()))
c2.metric("Minutes with an audio mood", pct(plays.loc[has_a, "duration_minutes"].sum()))
c3.metric("Minutes with both", pct(plays.loc[has_g & has_a, "duration_minutes"].sum()))
n_tracks = plays["track_id"].nunique()
n_feat = plays.loc[has_a, "track_id"].nunique()
c4.metric("Tracks with audio features", f"{n_feat} of {n_tracks}")

with st.expander("Fetch status (all tracks ever played)"):
    status_counts = dict(zip(fetch_status["status"], fetch_status["tracks"]))
    found = int(status_counts.get("found", 0))
    not_found = int(status_counts.get("not_found", 0))
    unfetched = max(total_tracks - found - not_found, 0)
    st.write(
        f"Total distinct tracks: **{total_tracks}**  |  features found: **{found}**  |  "
        f"ReccoBeats had nothing: **{not_found}**  |  not fetched yet: **{unfetched}**"
    )

st.markdown("---")

# ---------------------------------------------------------------- Daily side by side
st.subheader("Daily mood, side by side")


def daily_minutes(df, mood_col):
    d = df[df[mood_col].notna()].groupby(["day", mood_col], as_index=False)["duration_minutes"].sum()
    if d.empty:
        return d
    d = d.rename(columns={mood_col: "Mood", "duration_minutes": "Minutes"})
    d["Mood"] = d["Mood"].str.capitalize()
    d["Date"] = d["day"].dt.strftime("%b %d")
    d["Share"] = 100 * d["Minutes"] / d.groupby("day")["Minutes"].transform("sum")
    return d


genre_daily = daily_minutes(plays, "genre_mood")
audio_daily = daily_minutes(plays, "audio_mood")
date_labels = [pd.Timestamp(d).strftime("%b %d") for d in sorted(plays["day"].unique())]

view = st.radio("Show as", ["Minutes", "Share of covered minutes (%)"], horizontal=True)
use_share = view.startswith("Share")
y_col = "Share" if use_share else "Minutes"
y_title = "Share of covered minutes (%)" if use_share else "Minutes"
if use_share:
    y_max = 100
else:
    maxima = [d.groupby("day")["Minutes"].sum().max() for d in (genre_daily, audio_daily) if not d.empty]
    y_max = (max(maxima) if maxima else 1) * 1.1

col_g, col_a = st.columns(2)
for col, data, title in ((col_g, genre_daily, "Genre method"), (col_a, audio_daily, "Audio method")):
    with col:
        if data.empty:
            st.info(f"No data for the {title.lower()} in this window.")
            continue
        fig = px.bar(
            data, x="Date", y=y_col, color="Mood",
            color_discrete_map=MOOD_COLORS,
            category_orders={"Date": date_labels, "Mood": MOOD_LABELS},
            labels={y_col: y_title, "Date": ""},
            title=title,
        )
        fig.update_layout(legend_title_text="", yaxis_range=[0, y_max], margin=dict(t=50))
        st.plotly_chart(fig, width="stretch", key=f"daily_{title}")

st.caption(
    "Both charts share the same vertical scale. Days where one method has far less coverage than the other "
    "show up as a shorter stack, so check the Coverage numbers before reading a difference as meaningful."
)


def dominant(df, mood_col):
    d = df[df[mood_col].notna()].groupby(["day", mood_col], as_index=False)["duration_minutes"].sum()
    if d.empty:
        return pd.Series(dtype=object)
    idx = d.groupby("day")["duration_minutes"].idxmax()
    return d.loc[idx].set_index("day")[mood_col]


dom = pd.concat(
    [dominant(plays, "genre_mood").rename("Genre method"), dominant(plays, "audio_mood").rename("Audio method")],
    axis=1,
).sort_index(ascending=False)


def same(row):
    if pd.isna(row["Genre method"]) or pd.isna(row["Audio method"]):
        return "—"
    return "✅ Same" if row["Genre method"] == row["Audio method"] else "❌ Different"


dom["Same?"] = dom.apply(same, axis=1)
dom = dom.reset_index().rename(columns={"index": "day"})
dom["Date"] = pd.to_datetime(dom["day"]).dt.strftime("%b %d")
for c in ("Genre method", "Audio method"):
    dom[c] = dom[c].str.capitalize().fillna("—")
st.markdown("**Dominant mood per day**")
st.dataframe(dom[["Date", "Genre method", "Audio method", "Same?"]], width="stretch", hide_index=True)

if not has_audio:
    st.stop()

st.markdown("---")

# ---------------------------------------------------------------- Agreement
st.subheader("Where the methods agree and disagree")
both_df = plays[has_g & has_a]
if both_df.empty:
    st.info("No plays have both a genre mood and an audio mood yet, so agreement can't be measured.")
else:
    tracks = both_df.groupby("track_id").agg(
        track_name=("track_name", "first"),
        artist_names=("artist_names", "first"),
        genre_mood=("genre_mood", "first"),
        audio_mood=("audio_mood", "first"),
        valence=("valence", "first"),
        energy=("energy", "first"),
        plays=("track_id", "size"),
    ).reset_index()
    track_agree = (tracks["genre_mood"] == tracks["audio_mood"]).mean()
    play_agree = (both_df["genre_mood"] == both_df["audio_mood"]).mean()

    kappa = cohen_kappa(tracks["genre_mood"], tracks["audio_mood"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Agreement across distinct tracks", f"{100 * track_agree:.0f}%")
    m2.metric("Agreement weighted by plays", f"{100 * play_agree:.0f}%")
    m3.metric("Cohen's kappa (tracks)", "n/a" if kappa != kappa else f"{kappa:.2f}")
    m4.metric("Tracks compared", f"{len(tracks)}")
    st.caption(
        "Per-track agreement treats every song once. Play-weighted agreement lets heavily replayed songs dominate, "
        "so a large gap between the two means a few repeated tracks are driving the result. "
        "Kappa discounts the agreement you would get by chance: 1 is perfect, 0 is no better than chance. "
        "With few tracks, or when one method labels almost everything the same mood, kappa is unstable."
    )

    cm = pd.crosstab(tracks["genre_mood"], tracks["audio_mood"]).reindex(index=MOODS, columns=MOODS, fill_value=0)
    st.markdown("**Confusion matrix (distinct tracks)**")
    fig_cm = px.imshow(
        cm.values, x=MOOD_LABELS, y=MOOD_LABELS, text_auto=True,
        color_continuous_scale="Greens",
        labels=dict(x="Audio method says", y="Genre method says", color="Tracks"),
    )
    fig_cm.update_layout(margin=dict(t=20), height=380)
    st.plotly_chart(fig_cm, width="stretch", key="confusion")

    # ---------------------------------------------------------------- song by song
    st.markdown("**Song by song** (hover a title for its cover; the title links to Spotify)")
    f1, f2, f3 = st.columns([2, 2, 2])
    show = f1.radio("Show", ["All songs", "Only differences", "Only matches"], horizontal=True)
    g_sel = f2.multiselect("Last.fm genre mood", MOODS, default=MOODS)
    a_sel = f3.multiselect("ReccoBeats audio mood", MOODS, default=MOODS)
    songs = tracks.merge(track_meta, on="track_id", how="left").sort_values("plays", ascending=False)
    songs = songs[songs["genre_mood"].isin(g_sel) & songs["audio_mood"].isin(a_sel)]
    same_label = songs["genre_mood"] == songs["audio_mood"]
    if show == "Only differences":
        songs = songs[~same_label]
    elif show == "Only matches":
        songs = songs[same_label]
    if songs.empty:
        st.info("No songs match these filters.")
    else:
        songs = songs.head(60).copy()
        songs["Last.fm tags"] = songs["lastfm_tags"].fillna("no tags").map(lambda t: f'<span class="muted">{esc(t)}</span>')
        songs["Genre mood"] = songs["genre_mood"].map(mood_badge)
        songs["Audio mood"] = songs["audio_mood"].map(mood_badge)
        songs["Valence"] = songs["valence"].round(2)
        songs["Energy"] = songs["energy"].round(2)
        songs["Plays"] = songs["plays"]
        songs["Result"] = (songs["genre_mood"] == songs["audio_mood"]).map({
            True: '<span style="color:#1DB954;font-weight:600">Same</span>',
            False: '<span style="color:#FFC000;font-weight:600">Differs</span>'})
        st.markdown(
            track_table(songs, [("Artist's Last.fm tags", "Last.fm tags"), ("Last.fm genre mood", "Genre mood"),
                                ("ReccoBeats audio mood", "Audio mood"), ("Valence", "Valence"),
                                ("Energy", "Energy"), ("Plays", "Plays"), ("Result", "Result")],
                        html_cols=("Last.fm tags", "Genre mood", "Audio mood", "Result")),
            unsafe_allow_html=True,
        )
        st.caption(f"Showing {len(songs)} songs (most played first) of {len(tracks)} with both labels.")

    # ---------------------------------------------------------------- data for the toggles
    seed = lookup.load_genre_mood_map()
    arts = artist_tags.copy()
    arts["tags"] = arts["genres"].map(lambda g: [str(t) for t in g] if g is not None else [])
    # the database keeps only the tags that already passed the weight filter, so every stored tag counts as used
    voted = {r.artist_id: lookup.vote([(t, 100) for t in r.tags], seed) for r in arts.itertuples()}
    arts["winner"] = arts["artist_id"].map(lambda i: voted[i]["winner"])
    arts["how"] = arts["artist_id"].map(lambda i: voted[i]["how"])
    arts = arts.sort_values(["tracks", "artist_name"], ascending=[False, True]).reset_index(drop=True)

    st.divider()
    st.markdown("**Behind the labels.** Open a toggle for the Last.fm analysis, the ReccoBeats ratings, or the math.")

    with st.expander("Last.fm"):
        st.markdown(
            "Last.fm doesn't rate songs. It gives each **artist** a list of tags, and the genre mood is a vote among "
            "those tags. The chart shows the votes behind each artist's label; the table shows which tag voted for which mood."
        )
        if arts.empty:
            st.info("No Last.fm tags stored for the compared artists yet.")
        else:
            mismatch = int((arts["winner"] != arts["genre_mood"]).sum())
            if mismatch:
                st.warning(f"{mismatch} artist(s) get a different label here than the one stored by the pipeline, "
                           "so their tags or the seed list changed since the last dbt run.")
            how_counts = arts["how"].value_counts()
            c1, c2, c3 = st.columns(3)
            c1.metric("Artists", len(arts))
            c2.metric("Label rests on a single tag", int(how_counts.get("one tag decided it", 0)))
            c3.metric("Ties broken alphabetically", int(how_counts.get("tie, broken alphabetically", 0)))

            long_rows = []
            for r in arts.itertuples():
                v = voted[r.artist_id]
                for m in MOODS:
                    long_rows.append({"Artist": r.artist_name, "Votes for": m, "Tags": v["counts"][m]})
                long_rows.append({"Artist": r.artist_name, "Votes for": "ignored (no mood)",
                                  "Tags": sum(1 for t in v["per_tag"] if not t["mood"])})
            fig_votes = px.bar(
                pd.DataFrame(long_rows), y="Artist", x="Tags", color="Votes for", orientation="h",
                color_discrete_map={**TRACK_MOOD_COLORS, "ignored (no mood)": "#8a919c"},
                category_orders={"Artist": list(arts["artist_name"]), "Votes for": MOODS + ["ignored (no mood)"]},
                labels={"Tags": "Number of tags"},
            )
            fig_votes.update_yaxes(autorange="reversed", title=None)
            fig_votes.update_layout(height=max(320, 26 * len(arts) + 120), margin=dict(t=10, b=10),
                                    legend=dict(orientation="h", y=-0.12, title_text=""))
            st.plotly_chart(fig_votes, width="stretch", key="lastfm_votes")
            st.caption("Each bar is one artist's tags, split by the mood the seed list gives them. The tallest colour wins; "
                       "grey tags such as place names are ignored.")

            vote_rows = []
            for r in arts.itertuples():
                v = voted[r.artist_id]
                chips = "".join(tag_chip(t["tag"], t["mood"]) for t in v["per_tag"]) or '<span class="muted">no tags</span>'
                vote_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in (
                    esc(r.artist_name), str(int(r.tracks)), chips,
                    " &middot; ".join(f"{m} {v['counts'][m]}" for m in MOODS),
                    mood_badge(r.genre_mood), f'<span class="muted">{esc(v["how"])}</span>')) + "</tr>")
            head = "".join(f"<th>{h}</th>" for h in
                           ["Artist", "Songs here", "Last.fm tags (coloured = voted)", "Votes", "Label", "Decided by"])
            st.markdown(f'<table class="trk-table"><thead><tr>{head}</tr></thead><tbody>{"".join(vote_rows)}</tbody></table>',
                        unsafe_allow_html=True)
            st.caption("A dashed grey tag has no mood in the seed list, so it casts no vote. The database keeps only each "
                       "artist's top tags with a Last.fm weight of at least 10 (at most five) and not the weights themselves.")

    with st.expander("ReccoBeats"):
        st.markdown(
            "ReccoBeats gives every song nine ratings. The audio mood uses only **valence** and **energy**; the other seven "
            "are shown for context. The bars show where each 0-to-1 value sits."
        )
        if ratings.empty:
            st.info("No ReccoBeats ratings stored yet. Run ingest_features.py.")
        else:
            query = st.text_input("Filter by song or artist", key="rb_filter")
            view_df = ratings.copy()
            view_df["audio_mood"] = [lookup.audio_mood(v, e) for v, e in zip(view_df["valence"], view_df["energy"])]
            if query:
                mask = (view_df["track_name"].str.contains(query, case=False, na=False)
                        | view_df["artist_names"].str.contains(query, case=False, na=False))
                view_df = view_df[mask]
            zero_one = ["valence", "energy", "danceability", "acousticness", "speechiness", "instrumentalness", "liveness"]
            config = {
                "track_name": st.column_config.TextColumn("Song"),
                "artist_names": st.column_config.TextColumn("Artist"),
                "loudness": st.column_config.NumberColumn("Loudness (dB)", format="%.1f"),
                "tempo": st.column_config.NumberColumn("Tempo (BPM)", format="%.0f"),
                "audio_mood": st.column_config.TextColumn("Audio mood"),
            }
            for col in zero_one:
                config[col] = st.column_config.ProgressColumn(col.capitalize(), min_value=0.0, max_value=1.0, format="%.2f")
            ordered = ["track_name", "artist_names"] + zero_one + ["loudness", "tempo", "audio_mood"]
            st.dataframe(add_cover_column(view_df[ordered], view_df["track_id"]), column_config={"Cover": COVER_COLUMN, **config},
                         width="stretch", hide_index=True, height=420)
            st.caption(f"{len(view_df)} songs ReccoBeats knows. Click a column heading to sort, and scroll sideways for the rest.")
            st.markdown(
                "**What each rating means.** ReccoBeats provides these under the same names as Spotify's former audio "
                "features, but its values are **estimates**.\n\n"
                + "\n".join(f"* **{label}:** {meaning}." for key, label, meaning in lookup.FEATURES
                            if key not in ("key", "mode"))
            )

    with st.expander("The math"):
        ROW_END = chr(92) * 2  # the LaTeX row separator
        st.markdown(r"**1. The audio mood.** Each song has a valence $v$ and an energy $e$, both between $0$ and $1$.")
        st.latex(
            r"\text{audio mood}(v,e)=\begin{cases}"
            r"\text{upbeat} & v\ge 0.5,\ e\ge 0.5" + ROW_END +
            r"\text{intense} & v< 0.5,\ e\ge 0.5" + ROW_END +
            r"\text{calm} & v\ge 0.5,\ e< 0.5" + ROW_END +
            r"\text{mellow} & v< 0.5,\ e< 0.5"
            r"\end{cases}"
        )
        st.markdown(
            r"**2. The Last.fm genre mood.** For an artist $a$, let $T_a$ be its top Last.fm tags (at most five, each with a "
            r"weight of at least $10$). Let $s(t)$ be the mood the hand-made seed list gives tag $t$; unclassified tags give none. "
            r"With $c_k(a)$ the number of tags voting for mood $k$, the artist's mood is the most frequent one:"
        )
        st.latex(
            r"c_k(a)=\sum_{t\in T_a}\mathbb{1}\left[s(t)=k\right],\qquad g(a)=\operatorname*{arg\,max}_{k}\,c_k(a),"
            r"\qquad \Delta(a)=c_{(1)}(a)-c_{(2)}(a)"
        )
        st.caption(r"Ties go to the alphabetically first mood. $\Delta$ is the margin between the two largest counts: "
                   r"$\Delta=0$ is a tie, and $c_{(1)}=1$ with every other count $0$ means a single tag decided it.")
        if not arts.empty:
            pick = st.selectbox("Work it out for an artist", list(arts["artist_name"]), index=0, key="math_artist")
            pick_row = arts[arts["artist_name"] == pick].iloc[0]
            pv = voted[pick_row["artist_id"]]
            st.dataframe(
                pd.DataFrame({"Tag": [t["tag"] for t in pv["per_tag"]],
                              "Mood from the seed list": [t["mood"] or "none (ignored)" for t in pv["per_tag"]]}),
                hide_index=True, width="content",
            )
            st.latex(r",\ ".join(r"c_{\text{%s}}=%d" % (m, pv["counts"][m]) for m in MOODS))
            if pv["winner"]:
                st.latex(r"g(a)=\text{%s}\qquad \Delta=%d-%d=%d" % (pv["winner"], pv["top"], pv["second"], pv["top"] - pv["second"]))
                st.caption(f"{pick}: {pv['how']}.")
            else:
                st.caption(f"{pick} has no tag that maps to a mood.")

        st.markdown(
            r"**3. Observed agreement.** Over the $N$ songs with both labels, with $g_i$ the Last.fm label and $r_i$ the "
            r"ReccoBeats label of song $i$:"
        )
        st.latex(r"p_o=\frac{1}{N}\sum_{i=1}^{N}\mathbb{1}\left[g_i=r_i\right]")
        st.markdown(
            r"**4. Agreement expected by chance.** Let $n_{k\cdot}$ be the number of songs Last.fm puts in mood $k$ and "
            r"$n_{\cdot k}$ the number ReccoBeats puts there. If the two labellings were independent they would agree with "
            r"probability:"
        )
        st.latex(r"p_e=\sum_{k}\frac{n_{k\cdot}}{N}\cdot\frac{n_{\cdot k}}{N}")
        n_t = len(tracks)
        g_counts = tracks["genre_mood"].value_counts().reindex(MOODS, fill_value=0)
        a_counts = tracks["audio_mood"].value_counts().reindex(MOODS, fill_value=0)
        st.dataframe(
            pd.DataFrame({"Mood": MOODS, "Last.fm count": g_counts.values, "ReccoBeats count": a_counts.values,
                          "Chance term": [(g / n_t) * (a / n_t) for g, a in zip(g_counts.values, a_counts.values)]}),
            hide_index=True, width="content",
            column_config={"Chance term": st.column_config.NumberColumn("Chance term", format="%.4f")},
        )
        st.markdown(r"**5. Cohen's kappa.** The agreement beyond chance, as a share of the most it could be:")
        st.latex(r"\kappa=\frac{p_o-p_e}{1-p_e}")
        n_same = int((tracks["genre_mood"] == tracks["audio_mood"]).sum())
        p_o = n_same / n_t
        p_e = float(sum((g / n_t) * (a / n_t) for g, a in zip(g_counts.values, a_counts.values)))
        terms = " + ".join(r"\frac{%d}{%d}\cdot\frac{%d}{%d}" % (g, n_t, a, n_t)
                           for g, a in zip(g_counts.values, a_counts.values) if g and a) or "0"
        st.markdown("**With your numbers:**")
        st.latex(r"p_o=\frac{%d}{%d}=%.3f" % (n_same, n_t, p_o))
        st.latex(r"p_e=" + terms + r"=%.3f" % p_e)
        if p_e >= 1:
            st.latex(r"\kappa\ \text{is undefined here, because } p_e=1")
        else:
            st.latex(r"\kappa=\frac{%.3f-%.3f}{1-%.3f}=%.3f" % (p_o, p_e, p_e, (p_o - p_e) / (1 - p_e)))
            if kappa == kappa and abs(kappa - (p_o - p_e) / (1 - p_e)) < 1e-9:
                st.caption("This hand calculation matches the kappa shown above.")
        st.caption(
            "A common rule of thumb (Landis and Koch, 1977): 0 to 0.2 slight, 0.2 to 0.4 fair, 0.4 to 0.6 moderate, "
            "0.6 to 0.8 substantial, above 0.8 almost perfect. With this few songs, treat the value as rough."
        )

st.markdown("---")

# ---------------------------------------------------------------- Scatter
st.subheader("Valence vs energy, coloured by the genre method")
feat = plays[has_a]
tracks_all = feat.groupby("track_id").agg(
    track_name=("track_name", "first"),
    artist_names=("artist_names", "first"),
    genre_mood=("genre_mood", "first"),
    valence=("valence", "first"),
    energy=("energy", "first"),
    plays=("track_id", "size"),
).reset_index()
tracks_all["Genre mood"] = tracks_all["genre_mood"].fillna("no genre label").str.capitalize()

fig_sc = px.scatter(
    tracks_all, x="valence", y="energy", color="Genre mood", size="plays", size_max=22,
    color_discrete_map=MOOD_COLORS,
    hover_data={"track_name": True, "artist_names": True, "plays": True, "valence": ":.2f", "energy": ":.2f"},
    labels={"valence": "Valence (musical positivity)", "energy": "Energy", "track_name": "Track", "artist_names": "Artist"},
)
fig_sc.update_xaxes(range=[0, 1])
fig_sc.update_yaxes(range=[0, 1])
fig_sc.add_hline(y=ENERGY_THRESHOLD, line_dash="dash", line_color="#888")
fig_sc.add_vline(x=VALENCE_THRESHOLD, line_dash="dash", line_color="#888")
for x, y, label in ((0.03, 0.97, "Intense"), (0.97, 0.97, "Upbeat"), (0.03, 0.03, "Mellow"), (0.97, 0.03, "Calm")):
    fig_sc.add_annotation(
        x=x, y=y, text=label, showarrow=False, font=dict(color="#aaa", size=14),
        xanchor="left" if x < 0.5 else "right", yanchor="top" if y > 0.5 else "bottom",
    )
fig_sc.update_layout(legend_title_text="", height=520, margin=dict(t=20))
st.plotly_chart(fig_sc, width="stretch", key="scatter")
st.caption(
    "If the genre method were reliable, each colour would cluster in its own corner. "
    "Colours spread across corners show where artist-level genre misses what the track itself sounds like."
)

st.markdown("---")

# ---------------------------------------------------------------- Continuous signal
st.subheader("The continuous signal: average valence and energy per day")
f2 = feat.copy()
f2["v_w"] = f2["valence"] * f2["duration_minutes"]
f2["e_w"] = f2["energy"] * f2["duration_minutes"]
daily_ve = f2.groupby("day").agg(v_w=("v_w", "sum"), e_w=("e_w", "sum"), m=("duration_minutes", "sum")).reset_index()
daily_ve["Valence"] = daily_ve["v_w"] / daily_ve["m"]
daily_ve["Energy"] = daily_ve["e_w"] / daily_ve["m"]
daily_ve["Date"] = daily_ve["day"].dt.strftime("%b %d")
fig_ve = px.line(
    daily_ve, x="Date", y=["Valence", "Energy"], markers=True,
    category_orders={"Date": date_labels}, labels={"value": "Minutes-weighted average (0 to 1)", "Date": ""},
)
fig_ve.update_yaxes(range=[0, 1])
fig_ve.update_layout(legend_title_text="", margin=dict(t=20))
st.plotly_chart(fig_ve, width="stretch", key="valence_energy_daily")
st.caption(
    "Averages near 0.5 mean the day is spread across moods, and a single 'dominant mood' label overstates it. "
    "Averages are computed over tracks that have audio features only."
)

st.markdown("---")

# ---------------------------------------------------------------- Missing coverage
st.subheader("Most-played tracks with no audio features")
missing = plays[~has_a].groupby("track_id").agg(
    Track=("track_name", "first"), Artist=("artist_names", "first"),
    **{"Genre mood": ("genre_mood", "first")}, Plays=("track_id", "size"),
).reset_index().sort_values("Plays", ascending=False).head(15)
missing_ids = missing.pop("track_id")
missing["Genre mood"] = missing["Genre mood"].str.capitalize().fillna("—")
if missing.empty:
    st.success("Every track in this window has audio features.")
else:
    st.dataframe(add_cover_column(missing, missing_ids), column_config={"Cover": COVER_COLUMN}, width="stretch", hide_index=True)
    st.caption(
        "If these are mostly the same kinds of artists, the audio method has a coverage bias, "
        "and its mood totals under-represent that part of your listening."
    )
