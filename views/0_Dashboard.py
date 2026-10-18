import os
import json

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from db import get_engine, to_ist, ist_day_label
from covers import is_allowed_cover_url
from track_ui import inject_css, track_html, track_table

load_dotenv()

MOOD_COLORS = {
    "calm": "#5B9BD5",
    "mellow": "#1DB954",
    "intense": "#E33A3A",
    "upbeat": "#FFC000",
}

SPOTIFY_GREEN = "#1DB954"

@st.cache_data(ttl=300)
def load_data():
    engine = get_engine()
    daily_listening = pd.read_sql("SELECT * FROM dbt_dev.daily_listening_summary ORDER BY listen_date", engine)
    daily_mood = pd.read_sql("SELECT * FROM dbt_dev.daily_mood_summary ORDER BY listen_date", engine)
    dominant_mood = pd.read_sql("SELECT * FROM dbt_dev.daily_dominant_mood ORDER BY listen_date DESC", engine)
    daily_top_track = pd.read_sql("""
        SELECT t.*, a.album_name, c.cover_url
        FROM dbt_dev.daily_top_track t
        LEFT JOIN (SELECT track_id, max(album_name) AS album_name
                   FROM dbt_dev.stg_recently_played GROUP BY track_id) a ON a.track_id = t.track_id
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = t.track_id
        ORDER BY t.listen_date DESC
    """, engine)

    today_tracks = pd.read_sql("""
        SELECT s.played_at, s.track_id, s.track_name, s.artist_names, s.album_name, c.cover_url
        FROM dbt_dev.stg_recently_played s
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = s.track_id
        WHERE s.played_at::date = (SELECT max(played_at::date) FROM dbt_dev.stg_recently_played)
        ORDER BY s.played_at DESC
    """, engine)

    top_tracks_week = pd.read_sql("""
        SELECT s.track_id, s.track_name, s.artist_names, max(s.album_name) AS album_name,
               max(c.cover_url) AS cover_url, count(*) AS plays
        FROM dbt_dev.stg_recently_played s
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = s.track_id
        WHERE s.played_at >= now() - interval '7 days'
        GROUP BY s.track_id, s.track_name, s.artist_names
        ORDER BY plays DESC, s.track_name
        LIMIT 10
    """, engine)

    top_artists_week = pd.read_sql("""
        SELECT artist_names, count(*) as plays, round(sum(duration_minutes)::numeric, 1) as minutes
        FROM dbt_dev.stg_recently_played
        WHERE played_at >= now() - interval '7 days'
        GROUP BY artist_names
        ORDER BY minutes DESC
        LIMIT 10
    """, engine)

    # all_plays = the downloaded history plus live plays, so "new" means new against your whole history
    discovered_recently = pd.read_sql("""
        SELECT s.track_id, max(s.track_name) AS track_name, max(s.artist_name) AS artist_names,
               max(s.album_name) AS album_name, max(c.cover_url) AS cover_url,
               count(*) FILTER (WHERE s.is_real_play) AS plays, min(s.played_at) AS first_played
        FROM dbt_dev.all_plays s
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = s.track_id
        GROUP BY s.track_id
        HAVING count(*) FILTER (WHERE s.is_real_play) > 1
           AND min(s.played_at) >= now() - interval '7 days'
        ORDER BY plays DESC, first_played DESC
    """, engine)

    liked_tracks = pd.read_sql("""
        SELECT l.track_id, l.track_name, l.artist_names, l.liked_at,
               a.album_name, c.cover_url
        FROM liked_tracks l
        LEFT JOIN (SELECT track_id, max(album_name) AS album_name
                   FROM dbt_dev.stg_recently_played GROUP BY track_id) a ON a.track_id = l.track_id
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = l.track_id
        ORDER BY l.liked_at DESC
    """, engine)

    daily_audio_mood = pd.read_sql("SELECT * FROM dbt_dev.daily_audio_mood_summary ORDER BY listen_date", engine)

    # The songs behind each coloured block of the mood charts. These use the same joins as the marts
    # (daily_mood_summary / daily_audio_mood_summary), so the minutes add up to what the chart shows.
    mood_tracks = pd.read_sql("""
        SELECT date_trunc('day', p.played_at) AS listen_date, m.mood, p.track_id,
               max(p.track_name) AS track_name, max(p.artist_names) AS artist_names,
               count(*) AS plays, round(sum(p.duration_minutes)::numeric, 1) AS minutes,
               max(c.cover_url) AS cover_url
        FROM dbt_dev.stg_recently_played p
        JOIN dbt_dev.stg_artist_moods m ON m.artist_id = p.primary_artist_id
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = p.track_id
        GROUP BY 1, 2, 3
        ORDER BY 1, minutes DESC
    """, engine)

    audio_tracks = pd.read_sql("""
        SELECT p.listen_date, p.audio_mood AS mood, p.track_id,
               max(p.track_name) AS track_name, max(p.artist_names) AS artist_names,
               count(*) AS plays, round(sum(p.duration_minutes)::numeric, 1) AS minutes,
               max(c.cover_url) AS cover_url
        FROM dbt_dev.play_mood_comparison p
        LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = p.track_id
        WHERE p.audio_mood IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, minutes DESC
    """, engine)

    audio_coverage = pd.read_sql("""
        SELECT count(*) AS plays, count(audio_mood) AS plays_with_audio
        FROM dbt_dev.play_mood_comparison
    """, engine)

    return (daily_listening, daily_mood, dominant_mood, daily_top_track,
            today_tracks, top_tracks_week, top_artists_week,
            discovered_recently, liked_tracks, daily_audio_mood, audio_coverage,
            mood_tracks, audio_tracks)

def toggle_like(engine, track_id, track_name, artist_names):
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM liked_tracks WHERE track_id = :tid"),
            {"tid": track_id}
        ).fetchone()
        if exists:
            conn.execute(text("DELETE FROM liked_tracks WHERE track_id = :tid"), {"tid": track_id})
        else:
            conn.execute(
                text("""
                    INSERT INTO liked_tracks (track_id, track_name, artist_names)
                    VALUES (:tid, :tname, :aname)
                """),
                {"tid": track_id, "tname": track_name, "aname": artist_names}
            )
    st.cache_data.clear()

st.markdown("""
<style>
    html { scroll-behavior: smooth; }
    .block-container { padding-top: 2rem; }
    h1, h2, h3 { font-weight: 700; }
    [data-testid="stMetricValue"] { color: #1DB954; }
</style>
""", unsafe_allow_html=True)
inject_css()

(daily_listening, daily_mood, dominant_mood, daily_top_track,
 today_tracks, top_tracks_week, top_artists_week,
 discovered_recently, liked_tracks, daily_audio_mood, audio_coverage,
 mood_tracks, audio_tracks) = load_data()

st.title("🎧 My Listening & Mood")

st.components.v1.html("""
<style>
    .nav-pill {
        background:#333; color:white; padding:6px 14px; border-radius:20px;
        margin-right:8px; font-size:0.85rem; cursor:pointer; display:inline-block;
        font-family:'Source Sans Pro', sans-serif; transition: background 0.2s ease, transform 0.15s ease;
    }
    .nav-pill:hover { background:#1DB954; transform: translateY(-1px); }
</style>
<div style="margin-bottom: 0.5rem;">
    <span class="nav-pill" onclick="smoothScrollTo('discovered-recently')">🔍 Discovered</span>
    <span class="nav-pill" onclick="smoothScrollTo('liked-songs')">❤️ Liked</span>
</div>
<script>
    function getScrollParent(el, doc) {
        while (el && el !== doc.body) {
            const style = window.parent.getComputedStyle(el);
            if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight) {
                return el;
            }
            el = el.parentElement;
        }
        return doc.scrollingElement || doc.documentElement;
    }

    function smoothScrollTo(id) {
        const doc = window.parent.document;
        const target = doc.getElementById(id);
        if (!target) return;

        const container = getScrollParent(target.parentElement, doc);
        const containerRect = container.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const startY = container.scrollTop;
        const targetY = startY + (targetRect.top - containerRect.top) - 20;
        const distance = targetY - startY;
        const duration = 700;
        let startTime = null;

        function easeInOutCubic(t) {
            return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2;
        }

        function step(timestamp) {
            if (!startTime) startTime = timestamp;
            const elapsed = timestamp - startTime;
            const t = Math.min(elapsed / duration, 1);
            container.scrollTop = startY + distance * easeInOutCubic(t);
            if (t < 1) window.parent.requestAnimationFrame(step);
        }
        window.parent.requestAnimationFrame(step);
    }
</script>
""", height=45)

# --- Today's dominant mood banner ---
if not dominant_mood.empty:
    latest = dominant_mood.iloc[0]
    mood = latest["dominant_mood"]
    color = MOOD_COLORS.get(mood, "#999999")
    st.markdown(
        f"""
        <div style="background: linear-gradient(90deg, {color}33, {color}0D);
                    padding:24px 28px; border-radius:14px; border-left:6px solid {color};">
            <p style="margin:0; font-size:0.85rem; letter-spacing:1px; text-transform:uppercase; opacity:0.7;">
                Today's vibe
            </p>
            <h2 style="margin:4px 0 0 0; color:{color};">{mood.capitalize()} 🎵</h2>
            <p style="margin:6px 0 0 0; opacity:0.8;">{latest['dominant_mood_minutes']} minutes of {mood} listening today</p>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.info("No mood data yet — keep listening and check back soon.")

st.write("")

# --- Mood over time (animated, custom HTML/JS), used for both mood methods ---
def render_mood_chart(daily_mood, tracks, empty_message):
    if not daily_mood.empty:
        import json

        df = daily_mood.copy()
        # only the last 10 days with listening, so the chart stays readable as the history grows
        df = df[df["listen_date"].isin(sorted(df["listen_date"].unique())[-10:])]
        df["Date"] = ist_day_label(df["listen_date"])
        df["Mood"] = df["mood"].str.capitalize()

        df["day_total"] = df.groupby("listen_date")["minutes_listened"].transform("sum")
        df["Percent"] = round(100 * df["minutes_listened"] / df["day_total"], 1)

        dates = list(df.sort_values("listen_date")["Date"].unique())
        moods_present = [m for m in ["Calm", "Mellow", "Intense", "Upbeat"] if m in df["Mood"].unique()]
        color_map_cap = {k.capitalize(): v for k, v in MOOD_COLORS.items()}

        def build_traces(value_col):
            traces = []
            for mood in moods_present:
                sub = df[df["Mood"] == mood].set_index("Date")
                y_vals = [round(float(sub.loc[d, value_col]), 1) if d in sub.index else 0 for d in dates]
                traces.append({
                    "x": dates, "y": y_vals, "name": mood,
                    "type": "bar", "marker": {"color": color_map_cap[mood]}
                })
            return traces

        minutes_traces = build_traces("minutes_listened")
        percent_traces = build_traces("Percent")

        # songs behind each coloured block, keyed "Oct 11|Intense" and embedded in the page, so a click needs no round trip
        mt = tracks.copy()
        mt["Date"] = ist_day_label(mt["listen_date"])
        mt["Mood"] = mt["mood"].str.capitalize()
        songs = {}
        for (day, mood_name), grp in mt.groupby(["Date", "Mood"]):
            songs[f"{day}|{mood_name}"] = [
                {"id": r.track_id, "name": r.track_name, "artist": r.artist_names,
                 "plays": int(r.plays), "min": float(r.minutes),
                 "img": r.cover_url if isinstance(r.cover_url, str) and is_allowed_cover_url(r.cover_url) else ""}
                for r in grp.itertuples()
            ]
        # keep "</" out of the embedded JSON so a track title can never close the script tag
        songs_json = json.dumps(songs).replace("</", "<" + chr(92) + "/")

        chart_html = f"""
        <style>
            .mood-btn {{
                background:#333; color:white; border:none; padding:6px 16px;
                border-radius:20px; margin-right:8px; cursor:pointer; font-family:sans-serif;
                transition: background 0.2s ease, transform 0.15s ease;
            }}
            .mood-btn:hover {{ background:#2a8a3f; transform: translateY(-1px); }}
            .mood-btn.active {{ background:#1DB954; }}
            .mood-btn.active:hover {{ background:#1DB954; }}
            #mood-chart .nsewdrag {{ cursor: pointer !important; }}
            #mood-hint {{ font:13px sans-serif; color:#9aa4ad; margin:4px 0 8px; }}
            #mood-songs {{ max-height:280px; overflow-y:auto; font-family:sans-serif; color:#e0e0e0; }}
            .songs-head {{ display:flex; align-items:center; gap:8px; font-weight:600; margin:6px 0; }}
            .songs-head .dot {{ width:10px; height:10px; border-radius:50%; }}
            .song-row {{ display:flex; align-items:center; gap:10px; padding:6px 0; border-top:1px solid #2a2f35; }}
            .song-row img, .song-row .ph {{ width:40px; height:40px; border-radius:4px; object-fit:cover; background:#2a2f35; flex:none; }}
            .song-row .txt {{ flex:1; min-width:0; }}
            .song-row .txt a {{ color:#e0e0e0; font-weight:600; text-decoration:none; }}
            .song-row .txt a:hover {{ text-decoration:underline; }}
            .song-row .txt span {{ display:block; font-size:12px; color:#9aa4ad; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
            .song-row .meta {{ font-size:12px; color:#9aa4ad; white-space:nowrap; }}
        </style>
        <div id="mood-toggle" style="margin-bottom:10px;">
            <button id="btn-minutes" class="mood-btn active" onclick="showView('minutes')">Minutes</button>
            <button id="btn-percent" class="mood-btn" onclick="showView('percent')">% of day</button>
        </div>
        <div id="mood-chart" style="width:100%;height:420px;"></div>
        <div id="mood-hint">Click a coloured block to see the songs behind it.</div>
        <div id="mood-songs"></div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.27.0/plotly.min.js"></script>
        <script>
            const minutesData = {json.dumps(minutes_traces)};
            const percentData = {json.dumps(percent_traces)};
            const songs = {songs_json};
            const moodColors = {json.dumps(color_map_cap)};
            let currentData = JSON.parse(JSON.stringify(minutesData));
            let currentMode = "minutes";
            let animating = false;

            const layout = {{
                barmode: "stack",
                margin: {{t: 10, b: 40}},
                paper_bgcolor: "rgba(0,0,0,0)",
                plot_bgcolor: "rgba(0,0,0,0)",
                font: {{color: "#e0e0e0"}},
                xaxis: {{gridcolor: "#333"}},
                yaxis: {{title: "Minutes", gridcolor: "#333"}},
                legend: {{orientation: "h", y: -0.2}}
            }};
            Plotly.newPlot("mood-chart", currentData, layout, {{responsive: true, displayModeBar: false}});

            // Built with textContent / DOM nodes (never innerHTML), so titles and artist names can't inject markup.
            function renderSongs(day, mood) {{
                const box = document.getElementById("mood-songs");
                const list = songs[day + "|" + mood] || [];
                box.textContent = "";
                document.getElementById("mood-hint").textContent = "";
                const head = document.createElement("div");
                head.className = "songs-head";
                const dot = document.createElement("span");
                dot.className = "dot";
                dot.style.background = moodColors[mood] || "#999";
                const total = list.reduce((a, s) => a + s.min, 0);
                head.appendChild(dot);
                head.appendChild(document.createTextNode(
                    mood + " - " + day + " - " + list.length + (list.length === 1 ? " song" : " songs") + ", " + total.toFixed(1) + " min"));
                box.appendChild(head);
                list.forEach(s => {{
                    const row = document.createElement("div");
                    row.className = "song-row";
                    if (s.img) {{
                        const im = document.createElement("img");
                        im.src = s.img; im.alt = "";
                        row.appendChild(im);
                    }} else {{
                        const ph = document.createElement("div");
                        ph.className = "ph";
                        row.appendChild(ph);
                    }}
                    const txt = document.createElement("div");
                    txt.className = "txt";
                    const a = document.createElement("a");
                    a.href = "https://open.spotify.com/track/" + encodeURIComponent(s.id);
                    a.target = "_blank"; a.rel = "noopener"; a.textContent = s.name;
                    const sub = document.createElement("span");
                    sub.textContent = s.artist;
                    txt.appendChild(a); txt.appendChild(sub);
                    const meta = document.createElement("div");
                    meta.className = "meta";
                    meta.textContent = s.plays + (s.plays === 1 ? " play" : " plays") + ", " + s.min.toFixed(1) + " min";
                    row.appendChild(txt); row.appendChild(meta);
                    box.appendChild(row);
                }});
            }}
            document.getElementById("mood-chart").on("plotly_click", ev => {{
                const pt = ev.points[0];
                renderSongs(pt.x, pt.data.name);
            }});

            function showView(mode) {{
                if (animating || mode === currentMode) return;
                animating = true;
                const targetData = mode === "minutes" ? minutesData : percentData;
                const startData = JSON.parse(JSON.stringify(currentData));
                const frames = 20;
                const durationMs = 450;
                let frame = 0;

                document.getElementById("btn-minutes").classList.toggle("active", mode === "minutes");
                document.getElementById("btn-percent").classList.toggle("active", mode === "percent");

                function easeInOutCubic(t) {{
                    return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2;
                }}

                function step() {{
                    frame++;
                    const t = easeInOutCubic(frame / frames);
                    const interpolated = startData.map((trace, i) => {{
                        return Object.assign({{}}, trace, {{
                            y: trace.y.map((v, j) => v + (targetData[i].y[j] - v) * t)
                        }});
                    }});
                    const newLayout = Object.assign({{}}, layout, {{
                        yaxis: {{title: mode === "minutes" ? "Minutes" : "Share of day (%)", gridcolor: "#333"}}
                    }});
                    Plotly.react("mood-chart", interpolated, newLayout, {{responsive: true, displayModeBar: false}});

                    if (frame < frames) {{
                        setTimeout(step, durationMs / frames);
                    }} else {{
                        currentData = targetData;
                        currentMode = mode;
                        animating = false;
                    }}
                }}
                step();
            }}
        </script>
        """

        st.components.v1.html(chart_html, height=800)
    else:
        st.info(empty_message)



st.subheader("Mood over time")
st.caption("From each artist's Last.fm genre tags. Shows the last 10 days with listening.")
render_mood_chart(daily_mood, mood_tracks, "No mood breakdown available yet.")

st.subheader("Audio mood over time")
if not audio_coverage.empty and audio_coverage.iloc[0]["plays"] > 0:
    _total = int(audio_coverage.iloc[0]["plays"])
    _with = int(audio_coverage.iloc[0]["plays_with_audio"])
    st.caption(
        f"From each track's own valence and energy (ReccoBeats). Covers {_with} of {_total} plays "
        f"({100 * _with / _total:.0f}%): ReccoBeats has no ratings for many recent releases."
    )
render_mood_chart(daily_audio_mood, audio_tracks, "No audio mood yet. Run ingest_features.py, then dbt.")

st.write("")
st.markdown("---")

# --- Overall listening activity ---
st.subheader("Listening activity")
if not daily_listening.empty:
    df = daily_listening.copy()
    df["Date"] = ist_day_label(df["listen_date"])

    col1, col2 = st.columns(2)
    with col1:
        fig_minutes = px.line(
            df, x="Date", y="total_minutes_listened", markers=True,
            labels={"total_minutes_listened": "Minutes listened", "Date": ""},
            title="Minutes per day",
        )
        fig_minutes.update_traces(line_color=SPOTIFY_GREEN, marker_color=SPOTIFY_GREEN)
        st.plotly_chart(fig_minutes, width="stretch")
    with col2:
        df_variety = df.rename(columns={"distinct_tracks": "Tracks", "distinct_artists": "Artists"})
        fig_variety = px.line(
            df_variety, x="Date", y=["Tracks", "Artists"], markers=True,
            labels={"value": "Count", "Date": ""},
            title="Variety per day",
        )
        fig_variety.update_layout(legend_title_text="")
        st.plotly_chart(fig_variety, width="stretch")
else:
    st.info("No listening data yet.")

st.markdown("---")

# --- Top track per day ---
st.subheader("Song of the day")
if not daily_top_track.empty:
    df = daily_top_track.copy()
    df["Date"] = ist_day_label(df["listen_date"])
    df["Plays"] = df["play_count"]
    st.markdown(track_table(df, [("Date", "Date"), ("Plays", "Plays")], scroll_height=340), unsafe_allow_html=True)
else:
    st.info("No data yet.")

st.markdown("---")

# --- This week: top tracks & artists ---
st.subheader("This week's rotation")
col3, col4 = st.columns(2)
with col3:
    st.markdown("**🎵 Top tracks**")
    if not top_tracks_week.empty:
        st.markdown(track_table(top_tracks_week, [("Plays", "plays")]), unsafe_allow_html=True)
    else:
        st.info("No data yet.")
with col4:
    st.markdown("**🎤 Top artists**")
    if not top_artists_week.empty:
        df = top_artists_week.rename(columns={"artist_names": "Artist", "plays": "Plays", "minutes": "Minutes"})
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("No data yet.")

st.markdown("---")

# --- Today's actual tracks ---
with st.expander("🕒 Today's full play history"):
    if not today_tracks.empty:
        df = today_tracks.copy()
        df["Time"] = to_ist(df["played_at"]).dt.strftime("%H:%M")
        st.markdown(track_table(df, [("Time", "Time")], scroll_height=340), unsafe_allow_html=True)
    else:
        st.info("No plays recorded today yet.")

st.markdown("---")

# --- Discovered recently: new to your history, already played more than once ---
st.markdown('<div id="discovered-recently"></div>', unsafe_allow_html=True)
st.subheader("🔍 Discovered recently")
st.caption("New to your whole history (including the imported Spotify export) in the last 7 days, and already played more than once.")
if not discovered_recently.empty:
    liked_ids = set(liked_tracks["track_id"]) if not liked_tracks.empty else set()

    def discovered_rows(frame):
        for _, row in frame.iterrows():
            col_a, col_b = st.columns([5, 1])
            with col_a:
                link = track_html(row["track_id"], row["track_name"], row["artist_names"],
                                  row["album_name"], row["cover_url"])
                st.markdown(f"{link} - {row['artist_names']} ({row['plays']} plays)", unsafe_allow_html=True)
            with col_b:
                label = "❤️" if row["track_id"] in liked_ids else "🤍"
                if st.button(label, key=f"like_{row['track_id']}"):
                    toggle_like(get_engine(), row["track_id"], row["track_name"], row["artist_names"])
                    st.rerun()

    discovered_rows(discovered_recently.head(15))
    if len(discovered_recently) > 15:
        with st.expander(f"Show {len(discovered_recently) - 15} more"):
            discovered_rows(discovered_recently.iloc[15:])
else:
    st.info("No repeated new discoveries in the last 7 days yet.")

st.markdown("---")

# --- Liked songs ---
st.markdown('<div id="liked-songs"></div>', unsafe_allow_html=True)
st.subheader("❤️ Liked songs")
if not liked_tracks.empty:
    df = liked_tracks.copy()
    df["Liked"] = ist_day_label(df["liked_at"])
    st.markdown(track_table(df, [("Liked", "Liked")]), unsafe_allow_html=True)
else:
    st.info("No liked songs yet — like something from 'Discovered recently' above.")