import os
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

MOOD_COLORS = {
    "calm": "#5B9BD5",
    "mellow": "#1DB954",
    "intense": "#E33A3A",
    "upbeat": "#FFC000",
}

SPOTIFY_GREEN = "#1DB954"

@st.cache_resource
def get_engine():
    conn_str = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(conn_str)

@st.cache_data(ttl=300)
def load_data():
    engine = get_engine()
    daily_listening = pd.read_sql("SELECT * FROM dbt_dev.daily_listening_summary ORDER BY listen_date", engine)
    daily_mood = pd.read_sql("SELECT * FROM dbt_dev.daily_mood_summary ORDER BY listen_date", engine)
    dominant_mood = pd.read_sql("SELECT * FROM dbt_dev.daily_dominant_mood ORDER BY listen_date DESC", engine)
    daily_top_track = pd.read_sql("SELECT * FROM dbt_dev.daily_top_track ORDER BY listen_date DESC", engine)

    today_tracks = pd.read_sql("""
        SELECT played_at, track_name, artist_names
        FROM dbt_dev.stg_recently_played
        WHERE played_at::date = (SELECT max(played_at::date) FROM dbt_dev.stg_recently_played)
        ORDER BY played_at DESC
    """, engine)

    top_tracks_week = pd.read_sql("""
        SELECT track_name, artist_names, count(*) as plays
        FROM dbt_dev.stg_recently_played
        WHERE played_at >= now() - interval '7 days'
        GROUP BY track_name, artist_names
        ORDER BY plays DESC
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

    discovered_recently = pd.read_sql("""
        SELECT track_id, track_name, artist_names, count(*) as plays, min(played_at) as first_played
        FROM dbt_dev.stg_recently_played
        GROUP BY track_id, track_name, artist_names
        HAVING count(*) > 1
           AND min(played_at) >= now() - interval '7 days'
        ORDER BY plays DESC, first_played DESC
    """, engine)

    liked_tracks = pd.read_sql("""
        SELECT track_id, track_name, artist_names, liked_at
        FROM liked_tracks
        ORDER BY liked_at DESC
    """, engine)

    return (daily_listening, daily_mood, dominant_mood, daily_top_track,
            today_tracks, top_tracks_week, top_artists_week,
            discovered_recently, liked_tracks)

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

st.set_page_config(page_title="My Listening & Mood", page_icon="🎧", layout="wide")

st.markdown("""
<style>
    html { scroll-behavior: smooth; }
    .block-container { padding-top: 2rem; }
    h1, h2, h3 { font-weight: 700; }
    [data-testid="stMetricValue"] { color: #1DB954; }
</style>
""", unsafe_allow_html=True)

(daily_listening, daily_mood, dominant_mood, daily_top_track,
 today_tracks, top_tracks_week, top_artists_week,
 discovered_recently, liked_tracks) = load_data()

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

# --- Mood over time (animated, custom HTML/JS) ---
st.subheader("Mood over time")

if not daily_mood.empty:
    import json

    df = daily_mood.copy()
    df["Date"] = pd.to_datetime(df["listen_date"]).dt.strftime("%b %d")
    df["Mood"] = df["mood"].str.capitalize()

    df["day_total"] = df.groupby("listen_date")["minutes_listened"].transform("sum")
    df["Percent"] = round(100 * df["minutes_listened"] / df["day_total"], 1)

    dates = sorted(df["Date"].unique(), key=lambda d: pd.to_datetime(d + " 2026"))
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
    </style>
    <div id="mood-toggle" style="margin-bottom:10px;">
        <button id="btn-minutes" class="mood-btn active" onclick="showView('minutes')">Minutes</button>
        <button id="btn-percent" class="mood-btn" onclick="showView('percent')">% of day</button>
    </div>
    <div id="mood-chart" style="width:100%;height:420px;"></div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.27.0/plotly.min.js"></script>
    <script>
        const minutesData = {json.dumps(minutes_traces)};
        const percentData = {json.dumps(percent_traces)};
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

    st.components.v1.html(chart_html, height=470)
else:
    st.info("No mood breakdown available yet.")

st.write("")
st.markdown("---")

# --- Overall listening activity ---
st.subheader("Listening activity")
if not daily_listening.empty:
    df = daily_listening.copy()
    df["Date"] = pd.to_datetime(df["listen_date"]).dt.strftime("%b %d")

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
    df["Date"] = pd.to_datetime(df["listen_date"]).dt.strftime("%b %d")
    df = df.rename(columns={"track_name": "Track", "artist_names": "Artist", "play_count": "Plays"})
    st.dataframe(df[["Date", "Track", "Artist", "Plays"]], width="stretch", hide_index=True)
else:
    st.info("No data yet.")

st.markdown("---")

# --- This week: top tracks & artists ---
st.subheader("This week's rotation")
col3, col4 = st.columns(2)
with col3:
    st.markdown("**🎵 Top tracks**")
    if not top_tracks_week.empty:
        df = top_tracks_week.rename(columns={"track_name": "Track", "artist_names": "Artist", "plays": "Plays"})
        st.dataframe(df, width="stretch", hide_index=True)
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
        df["Time"] = pd.to_datetime(df["played_at"]).dt.strftime("%H:%M")
        df = df.rename(columns={"track_name": "Track", "artist_names": "Artist"})
        st.dataframe(df[["Time", "Track", "Artist"]], width="stretch", hide_index=True)
    else:
        st.info("No plays recorded today yet.")

st.markdown("---")

# --- Discovered recently: new to your history, already played more than once ---
st.markdown('<div id="discovered-recently"></div>', unsafe_allow_html=True)
st.subheader("🔍 Discovered recently")
st.caption("New to your history in the last 7 days, and already played more than once.")
if not discovered_recently.empty:
    liked_ids = set(liked_tracks["track_id"]) if not liked_tracks.empty else set()
    with st.container(height=320):
        for _, row in discovered_recently.iterrows():
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.write(f"**{row['track_name']}** — {row['artist_names']} ({row['plays']} plays)")
            with col_b:
                is_liked = row["track_id"] in liked_ids
                label = "❤️" if is_liked else "🤍"
                if st.button(label, key=f"like_{row['track_id']}"):
                    toggle_like(get_engine(), row["track_id"], row["track_name"], row["artist_names"])
                    st.rerun()
else:
    st.info("No repeated new discoveries in the last 7 days yet.")

st.markdown("---")

# --- Liked songs ---
st.markdown('<div id="liked-songs"></div>', unsafe_allow_html=True)
st.subheader("❤️ Liked songs")
if not liked_tracks.empty:
    df = liked_tracks.copy()
    df["Liked"] = pd.to_datetime(df["liked_at"]).dt.strftime("%b %d")
    df = df.rename(columns={"track_name": "Track", "artist_names": "Artist"})
    st.dataframe(df[["Track", "Artist", "Liked"]], width="stretch", hide_index=True)
else:
    st.info("No liked songs yet — like something from 'Discovered recently' above.")