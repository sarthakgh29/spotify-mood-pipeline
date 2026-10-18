"""Lifetime Wrapped: every year of listening, from the downloaded history plus the live pipeline."""
import webbrowser

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import playlists
import wrapped as w
from db import get_engine
from track_ui import esc, inject_css, track_html

GREEN = "#1DB954"
GREY = "#8a919c"
inject_css()


# ------------------------------------------------------------------ data
@st.cache_resource(ttl=3600, show_spinner="Loading your listening history...")
def load_history():
    # shared and read-only: cache_resource avoids copying the whole frame on every click
    df = pd.read_sql(
        "select played_at, track_id, track_name, artist_name, album_name, seconds_played::float as seconds_played, "
        "is_real_play, skipped from dbt_dev.all_plays", get_engine())
    return w.prepare(df)


@st.cache_data(ttl=600, show_spinner=False)
def load_covers():
    c = pd.read_sql("select track_id, cover_url from track_covers where cover_url is not null", get_engine())
    return dict(zip(c["track_id"], c["cover_url"]))


try:
    d = load_history()
except Exception as exc:
    st.title("Lifetime wrapped")
    st.error("Could not load the listening history. Is Docker running, and have `import_history.py` and "
             f"`dbt build` been run? ({exc.__class__.__name__})")
    st.stop()

if d.empty:
    st.title("Lifetime wrapped")
    st.info("No plays yet. Run `python import_history.py Spotify_Extended`, then `dbt build`.")
    st.stop()

covers = load_covers()
real = w.real_plays(d)

# Streamlit re-runs this script on every click, so each analysis result is cached by its arguments.
# SIG changes when the data changes, which invalidates the cache.
SIG = (len(d), str(d["played_at"].max()))


def _memo(name, fn):
    @st.cache_data(show_spinner=False, max_entries=256)
    def inner(sig, name_, *args):
        return fn(*args)
    return lambda *args: inner(SIG, name, *args)


overview = _memo("overview", lambda: w.overview(real, d))
top_songs = _memo("top_songs", lambda *a: w.top_songs(real, *a))
top_artists = _memo("top_artists", lambda *a: w.top_artists(real, *a))
top_albums = _memo("top_albums", lambda *a: w.top_albums(real, *a))
artist_by_year = _memo("artist_by_year", lambda *a: w.artist_by_year(real, *a))
yearly_top_artist = _memo("yearly_top_artist", lambda: w.yearly_top_artist(real))
milestones = _memo("milestones", lambda: w.milestones(real, marks=(1, 1000, 10000, 25000, 50000)))
streaks = _memo("streaks", lambda: w.streaks(real))
busiest_days = _memo("busiest_days", lambda *a: w.busiest_days(real, *a))
by_year = _memo("by_year", lambda: w.by_year(real))
by_month = _memo("by_month", lambda *a: w.by_month(real, *a))
monthly_rulers = _memo("monthly_rulers", lambda *a: w.monthly_rulers(real, *a))
year_card = _memo("year_card", lambda *a: w.year_card(real, d, *a))
hour_weekday = _memo("hour_weekday", lambda: w.hour_weekday(real))
time_bands = _memo("time_bands", lambda: w.time_bands(real))
daily_counts = _memo("daily_counts", lambda *a: w.daily_counts(real, *a))
skip_rates = _memo("skip_rates", lambda: w.skip_rates(d))
discovery = _memo("discovery", lambda: w.discovery(real))
obsessions = _memo("obsessions", lambda *a: w.obsessions(real, *a))
comfort_songs = _memo("comfort_songs", lambda *a: w.comfort_songs(real, *a))
forgotten = _memo("forgotten", lambda mp, qd: w.forgotten_favourites(real, mp, qd, n=100000))
artist_options = _memo("artist_options", lambda: w.artist_options(real))
song_options = _memo("song_options", lambda: w.song_options(real))
artist_lookup = _memo("artist_lookup", lambda a: w.artist_lookup(real, a))
song_lookup = _memo("song_lookup", lambda k: w.song_lookup(real, k))
per_song_counts = _memo("per_song_counts", lambda: real.groupby("song_key").size())

ov = overview()


def fmt_int(n):
    return f"{int(n):,}"


def cell(r):
    return track_html(r.track_id, r.track_name, r.artist_name, r.album_name, covers.get(r.track_id))


def songs_table(df, extra=()):
    """HTML table: rank, song (cover card on hover, link to Spotify), artist, then extra (header, column, formatter)."""
    head = "<th>#</th><th>Song</th><th>Artist</th>" + "".join(f"<th>{esc(h)}</th>" for h, _, _ in extra)
    rows = []
    for i, r in enumerate(df.itertuples(index=False), 1):
        cells = [str(i), cell(r), esc(r.artist_name)] + [esc(fmt(getattr(r, col))) for _, col, fmt in extra]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f'<table class="trk-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def day_text(ts):
    return pd.Timestamp(ts).strftime("%d %b %Y")


def style(fig, height=380):
    fig.update_layout(height=height, margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", y=-0.2, title_text=""))
    return fig


# ------------------------------------------------------------------ header
st.title("Lifetime wrapped")
st.caption(
    f"{day_text(ov['first_day'])} to {day_text(ov['last_day'])}. A real play is a play of 30 seconds or more. "
    "Songs released twice are counted once. Times are in IST.")

m = st.columns(5)
m[0].metric("Hours listened", fmt_int(ov["hours"]), help=f"That is {ov['hours'] / 24:.0f} full days of music.")
m[1].metric("Real plays", fmt_int(ov["real_plays"]))
m[2].metric("Different songs", fmt_int(ov["distinct_songs"]))
m[3].metric("Different artists", fmt_int(ov["distinct_artists"]))
m[4].metric("Days you listened", fmt_int(ov["active_days"]),
            help=f"About {ov['plays_per_active_day']:.0f} real plays on each of those days.")

tab_life, tab_year, tab_when, tab_habits, tab_forgot, tab_look, tab_card = st.tabs(
    ["Lifetime", "Year by year", "When you listen", "Habits", "Forgotten favourites", "Look up", "Wrapped card"])

# ================================================================== Lifetime
with tab_life:
    st.subheader("The songs of your life")
    st.markdown(songs_table(top_songs(20), [("Real plays", "plays", fmt_int), ("Hours", "hours", lambda v: f"{v:.1f}")]),
                unsafe_allow_html=True)
    st.caption("Hover a song for its cover; click it to open it in Spotify. Covers fill in as `history_covers.py` runs.")

    left, right = st.columns(2)
    with left:
        st.subheader("Top artists")
        ta = top_artists(15)
        fig = px.bar(ta.iloc[::-1], x="plays", y="artist_name", orientation="h", color_discrete_sequence=[GREEN],
                     hover_data={"hours": ":.0f", "songs": True}, labels={"plays": "Real plays", "artist_name": ""})
        st.plotly_chart(style(fig, 460), width="stretch")
    with right:
        st.subheader("Artist eras")
        g, names = artist_by_year(8)
        fig = px.area(g, x="year", y="plays", color="artist_name", category_orders={"artist_name": names},
                      labels={"plays": "Real plays", "year": "", "artist_name": ""})
        st.plotly_chart(style(fig, 460), width="stretch")
        yt = yearly_top_artist()
        st.caption("Number one artist each year: " + ", ".join(f"{int(r.year)} {r.artist_name}" for r in yt.itertuples()))

    st.subheader("Milestones")
    ms = milestones()
    rows = "".join(
        f"<tr><td>#{fmt_int(r.play_number)}</td><td>{pd.Timestamp(r.when):%d %b %Y}</td><td>{cell(r)}</td>"
        f"<td>{esc(r.artist_name)}</td></tr>" for r in ms.itertuples())
    st.markdown('<table class="trk-table"><thead><tr><th>Play</th><th>Date</th><th>Song</th><th>Artist</th></tr></thead>'
                f"<tbody>{rows}</tbody></table>", unsafe_allow_html=True)

    s = streaks()
    c1, c2, c3 = st.columns(3)
    c1.metric("Longest daily streak", f"{s['streak_days']} days",
              help=f"Listening every day from {day_text(s['streak_start'])} to {day_text(s['streak_end'])}.")
    c2.metric("Longest break", f"{s['gap_days']} days",
              help=(f"{day_text(s['gap_start'])} to {day_text(s['gap_end'])}" if s["gap_start"] is not None else "No break."))
    top_day = busiest_days(1).iloc[0]
    c3.metric("Biggest day", f"{int(top_day['plays'])} plays", help=f"{day_text(top_day['day'])}, {top_day['hours']:.1f} hours.")
    st.markdown("**Your biggest listening days**")
    bd = busiest_days(8)
    st.dataframe(pd.DataFrame({"Day": bd["day"].dt.strftime("%d %b %Y"), "Real plays": bd["plays"], "Hours": bd["hours"].round(1)}),
                 hide_index=True, width="content")

# ================================================================== Year by year
with tab_year:
    yrs = by_year()
    years = [int(y) for y in yrs["year"]]
    year = int(st.selectbox("Year", years[::-1], key="year_pick"))

    fig = go.Figure(go.Bar(
        x=[str(y) for y in yrs["year"]], y=yrs["plays"],
        marker_color=[GREEN if int(y) == year else GREY for y in yrs["year"]],
        customdata=np.stack([yrs["hours"].round(0), yrs["songs"], yrs["artists"]], axis=-1),
        hovertemplate="%{x}<br>%{y:,} real plays<br>%{customdata[0]:,} hours<br>%{customdata[1]:,} songs, %{customdata[2]:,} artists<extra></extra>"))
    fig.update_layout(yaxis_title="Real plays", xaxis=dict(type="category"))
    st.plotly_chart(style(fig, 280), width="stretch")
    st.caption(f"Showing {year}. The history starts in {day_text(ov['first_day'])}, so the first year is partial, "
               "and so is the current one.")

    yr = year_card(year)
    k = st.columns(5)
    k[0].metric(f"{year} real plays", fmt_int(yr["plays"]))
    k[1].metric("Hours", fmt_int(yr["hours"]))
    k[2].metric("Different songs", fmt_int(yr["songs"]))
    k[3].metric("New to you", fmt_int(yr["new_songs"]), help="Songs you played for the first time this year.")
    k[4].metric("Best month", w.MONTHS[yr["best_month"] - 1])

    st.subheader(f"The song that ruled each month of {year}")
    rulers = monthly_rulers(year)
    mon = by_month(year)
    figm = go.Figure(go.Bar(x=w.MONTHS, y=mon["plays"], marker_color=GREEN,
                            hovertemplate="%{x}: %{y:,} real plays<extra></extra>"))
    figm.update_layout(yaxis_title="Real plays", xaxis=dict(type="category"))
    st.plotly_chart(style(figm, 240), width="stretch")

    if rulers.empty:
        st.info("No plays this year.")
    else:
        rows = ""
        for r in rulers.itertuples():
            rows += (f"<tr><td>{w.MONTHS[r.month - 1]}</td><td>{cell(r)}</td><td>{esc(r.artist_name)}</td>"
                     f"<td>{r.plays}</td><td>{r.share:.0%} of {fmt_int(r.month_plays)}</td></tr>")
        st.markdown('<table class="trk-table"><thead><tr><th>Month</th><th>Song that ruled</th><th>Artist</th>'
                    f"<th>Plays</th><th>Share of the month</th></tr></thead><tbody>{rows}</tbody></table>",
                    unsafe_allow_html=True)

        month_names = [w.MONTHS[int(mm) - 1] for mm in rulers["month"]]
        pick_m = st.selectbox("Look at one month", ["Whole year"] + month_names, key=f"month_pick_{year}")
        if pick_m != "Whole year":
            month = w.MONTHS.index(pick_m) + 1
            st.subheader(f"{pick_m} {year}: top songs and artists")
            a, b = st.columns([3, 2])
            with a:
                st.markdown(songs_table(top_songs(10, year, month), [("Plays", "plays", fmt_int)]), unsafe_allow_html=True)
            with b:
                tam = top_artists(10, year, month)
                st.dataframe(pd.DataFrame({"Artist": tam["artist_name"], "Plays": tam["plays"]}), hide_index=True, width="stretch")

    st.subheader(f"{year}: top songs and artists")
    a, b = st.columns([3, 2])
    with a:
        st.markdown(songs_table(top_songs(10, year), [("Plays", "plays", fmt_int), ("Hours", "hours", lambda v: f"{v:.1f}")]),
                    unsafe_allow_html=True)
    with b:
        ty = top_artists(10, year)
        st.dataframe(pd.DataFrame({"Artist": ty["artist_name"], "Plays": ty["plays"], "Songs": ty["songs"]}),
                     hide_index=True, width="stretch")

# ================================================================== When you listen
with tab_when:
    bands = time_bands()
    night = bands.iloc[0]
    st.subheader("When you listen")
    st.markdown(f"**{night['share']:.0%} of your real plays happen between midnight and 6am.** "
                f"That is {fmt_int(night['plays'])} plays.")
    c1, c2 = st.columns([2, 3])
    with c1:
        fig = px.bar(bands, x="share", y="band", orientation="h", color_discrete_sequence=[GREEN],
                     labels={"share": "Share of real plays", "band": ""})
        fig.update_layout(xaxis_tickformat=".0%", yaxis=dict(autorange="reversed"))
        st.plotly_chart(style(fig, 280), width="stretch")
    with c2:
        hw = hour_weekday()
        fig = px.imshow(hw.values, x=[f"{h}:00" for h in range(24)], y=w.WEEKDAYS, aspect="auto",
                        color_continuous_scale="Greens", labels=dict(color="Real plays"))
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(style(fig, 280), width="stretch")
        st.caption("Each cell is an hour of the week, darker meaning more listening.")

    st.subheader("Your year in days")
    cal_year = int(st.selectbox("Year", sorted(real["year"].unique(), reverse=True), key="cal_year"))
    counts = daily_counts(cal_year)
    start = pd.Timestamp(year=cal_year, month=1, day=1)
    days = pd.date_range(start, pd.Timestamp(year=cal_year, month=12, day=31))
    first_monday = start - pd.Timedelta(days=start.weekday())
    week = ((days - first_monday).days // 7).to_numpy()
    z = np.full((7, int(week.max()) + 1), np.nan)
    txt = np.full(z.shape, "", dtype=object)
    for dt_, wk, wd in zip(days, week, days.weekday):
        v = int(counts.get(dt_, 0))
        z[wd, wk] = v
        txt[wd, wk] = f"{dt_:%d %b %Y}: {v} real plays"
    figc = go.Figure(go.Heatmap(z=z, text=txt, hoverinfo="text", xgap=3, ygap=3, showscale=False,
                                colorscale=[[0, "rgba(128,128,128,0.18)"], [0.001, "#0e4429"], [1, "#39d353"]], zmin=0))
    figc.update_layout(yaxis=dict(autorange="reversed", tickmode="array", tickvals=list(range(7)), ticktext=w.WEEKDAYS),
                       xaxis=dict(showticklabels=False))
    st.plotly_chart(style(figc, 230), width="stretch")
    ds = counts.sort_values(ascending=False)
    st.caption(f"{cal_year}: you listened on {len(counts)} of the year's days" +
               (f", with {int(ds.iloc[0])} real plays on {day_text(ds.index[0])}, your biggest day that year." if len(ds) else "."))

# ================================================================== Habits
with tab_habits:
    sr = skip_rates()
    st.subheader("How much of what you start do you really listen to?")
    fig = go.Figure()
    fig.add_bar(x=sr["year"].astype(str), y=sr["share_real"], name="Played 30 seconds or more", marker_color=GREEN)
    fig.add_bar(x=sr["year"].astype(str), y=1 - sr["share_real"], name="Under 30 seconds", marker_color=GREY)
    fig.update_layout(barmode="stack", yaxis_tickformat=".0%", xaxis=dict(type="category"))
    st.plotly_chart(style(fig, 320), width="stretch")
    full = sr[sr["year"] < sr["year"].max()]
    st.caption("Spotify's own 'skipped' flag is missing for the early years of the export, so this uses the 30-second rule, "
               "which works for every year. " +
               (f"Your share of real plays went from {full.iloc[0]['share_real']:.0%} in {int(full.iloc[0]['year'])} to "
                f"{full.iloc[-1]['share_real']:.0%} in {int(full.iloc[-1]['year'])}." if len(full) > 1 else ""))

    st.subheader("Discovering new music")
    dv = discovery()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=dv["year"].astype(str), y=dv["new_songs"], name="New songs that year", marker_color=GREEN, secondary_y=False)
    fig.add_trace(go.Scatter(x=dv["year"].astype(str), y=dv["share_new"], name="Share of plays that were new songs",
                             mode="lines+markers", line=dict(color="#FFC000")), secondary_y=True)
    fig.update_yaxes(tickformat=".0%", secondary_y=True, range=[0, 1])
    fig.update_xaxes(type="category")
    st.plotly_chart(style(fig, 320), width="stretch")
    st.caption(f"The history starts in {day_text(ov['first_day'])}, so the first year looks like all discovery. "
               "After that, the share shows how much of each year went to songs you had never played before.")

    st.subheader("How much you repeat")
    per_song = per_song_counts()
    thresholds = [5, 20, 50, 100, 250]
    for col, t in zip(st.columns(len(thresholds)), thresholds):
        col.metric(f"{t}+ plays", fmt_int((per_song >= t).sum()), help=f"Songs played {t} or more times.")

    a, b = st.columns(2)
    with a:
        st.markdown("**One-day obsessions** (most plays of a single song in one day)")
        st.markdown(songs_table(obsessions(10), [("Plays that day", "plays_that_day", fmt_int), ("Day", "day", day_text)]),
                    unsafe_allow_html=True)
    with b:
        st.markdown("**Comfort songs** (played in five or more different years)")
        cs = comfort_songs(5, 10)
        if cs.empty:
            st.info("No song has come back in that many years yet.")
        else:
            st.markdown(songs_table(cs, [("Years", "years", fmt_int), ("Plays", "plays", fmt_int)]), unsafe_allow_html=True)

# ================================================================== Forgotten favourites
with tab_forgot:
    st.subheader("Songs you loved and left behind")
    c1, c2 = st.columns(2)
    min_plays = c1.slider("At least this many real plays", 5, 200, 30, step=5)
    quiet_months = c2.slider("Not played for at least (months)", 3, 48, 12)
    ff_all = forgotten(min_plays, int(quiet_months * 30.4))
    st.markdown(f"**{len(ff_all):,} songs** match. The ones you played most, then dropped:")
    ff = ff_all.head(40)
    if ff.empty:
        st.info("Nothing matches. Lower the numbers above.")
    else:
        st.markdown(songs_table(ff, [("Plays", "plays", fmt_int), ("Peak year", "peak_year", lambda v: str(int(v))),
                                     ("Last played", "last_day", day_text),
                                     ("Quiet for", "quiet_days", lambda v: f"{v / 30.4:.0f} months")]), unsafe_allow_html=True)
        st.caption("Hover for the cover and click to play it again.")

# ================================================================== Look up
def month_text(p):
    return pd.Period(p, "M").strftime("%b %Y")


def lookup_view(r, noun):
    """Shared layout for an artist or a song: headline numbers, months chart, years, time of day."""
    k = st.columns(5)
    k[0].metric("Real plays", fmt_int(r["plays"]))
    k[1].metric("Hours", f"{r['hours']:.1f}")
    k[2].metric("First played", day_text(r["first_day"]))
    k[3].metric("Last played", day_text(r["last_day"]))
    k[4].metric("Days played", fmt_int(r["active_days"]))

    pw = r["peak_window"]
    if pw:
        st.markdown(
            f"**Peak period: {month_text(pw[0])} to {month_text(pw[1])}.** {pw[2]:,} real plays in those three months, "
            f"{pw[3]:.0%} of everything you played of this {noun}. "
            f"Best single month: {month_text(r['peak_month'])} ({r['peak_month_plays']:,} plays). "
            f"Best single day: {day_text(r['peak_day'])} ({r['peak_day_plays']} plays).")

    mc = r["monthly"]
    colors = [GREEN if (pw and pw[0] <= p <= pw[1]) else GREY for p in mc.index]
    fig = go.Figure(go.Bar(x=[p.to_timestamp() for p in mc.index], y=mc.values, marker_color=colors,
                           customdata=[month_text(p) for p in mc.index],
                           hovertemplate="%{customdata}: %{y:,} real plays<extra></extra>"))
    fig.update_layout(yaxis_title="Real plays per month", xaxis_title="")
    st.plotly_chart(style(fig, 300), width="stretch")
    st.caption("Green marks the peak three months.")

    a, b = st.columns(2)
    with a:
        yr_ = r["yearly"]
        fig = px.bar(x=yr_.index.astype(str), y=yr_.values, color_discrete_sequence=[GREEN],
                     labels={"x": "", "y": "Real plays"})
        fig.update_xaxes(type="category")
        st.plotly_chart(style(fig, 240), width="stretch")
    with b:
        hs = r["hour_share"]
        fig = px.bar(x=[f"{h}:00" for h in hs.index], y=hs.values, color_discrete_sequence=[GREEN],
                     labels={"x": "", "y": "Share of plays"})
        fig.update_layout(yaxis_tickformat=".0%")
        st.plotly_chart(style(fig, 240), width="stretch")
        st.caption("Time of day you play it (IST).")


with tab_look:
    kind = st.radio("Look up", ["Artist", "Song"], horizontal=True, key="look_kind")
    if kind == "Artist":
        ao = artist_options()
        name = st.selectbox("Artist (type to search)", list(ao.index), index=None, key="look_artist",
                            format_func=lambda n: f"{n}  ({ao[n]:,} plays)", placeholder="Start typing an artist")
        if name:
            r = artist_lookup(name)
            st.subheader(name)
            st.caption(f"{r['songs']:,} different songs.")
            lookup_view(r, "artist")
            st.markdown("**Their songs you played most**")
            st.markdown(songs_table(r["top_songs"].head(15), [("Plays", "plays", fmt_int), ("Hours", "hours", lambda v: f"{v:.1f}")]),
                        unsafe_allow_html=True)

            st.subheader("Make a Spotify playlist")
            avail = len(r["top_songs"])
            c1, c2 = st.columns([3, 2])
            pl_name = c1.text_input("Playlist name", value=f"{name}: most played", key=f"pl_name_{name}",
                                    max_chars=playlists.MAX_NAME)
            n_songs = c2.slider("Songs (most played first)", 1, min(avail, 100), min(25, avail), key=f"pl_n_{name}") if avail > 1 else 1
            is_public = st.checkbox("Make it public (otherwise only you can see it)", value=False, key=f"pl_pub_{name}")
            chosen = r["top_songs"].head(n_songs)
            st.caption(f"Will create a {'public' if is_public else 'private'} playlist called "
                       f"\"{playlists.clean_name(pl_name)}\" with {len(chosen)} songs, from "
                       f"\"{chosen.iloc[0]['track_name']}\" down to \"{chosen.iloc[-1]['track_name']}\". "
                       "It is added to your Spotify account; nothing existing is changed.")
            if st.button("Create on Spotify", key=f"pl_go_{name}", type="primary"):
                try:
                    sp = playlists.get_client()
                    with st.spinner("Checking each song is still playable on Spotify..."):
                        ids, missing = playlists.resolve_playable(sp, chosen.to_dict("records"))
                    res = playlists.create_playlist(sp, pl_name, ids, public=is_public,
                                                    description=f"{name}: my most played songs, from my listening history")
                    webbrowser.open_new_tab(res["url"])   # the dashboard runs on this machine, so this opens a tab for you
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
    else:
        so = song_options()
        labels = {k: f"{t}  -  {a}  ({p:,} plays)" for k, t, a, p in zip(so["song_key"], so["track_name"], so["artist_name"], so["plays"])}
        key = st.selectbox("Song (type to search)", list(labels), index=None, key="look_song",
                           format_func=lambda k: labels[k], placeholder="Start typing a song")
        if key:
            r = song_lookup(key)
            sg = r["song"]
            st.subheader(f"{sg['track_name']}  -  {sg['artist_name']}")
            st.markdown(songs_table(pd.DataFrame([sg]), [("Plays", "plays", fmt_int)]), unsafe_allow_html=True)
            lookup_view(r, "song")

# ================================================================== Wrapped card
with tab_card:
    choices = ["Lifetime"] + [str(y) for y in sorted(real["year"].unique(), reverse=True)]
    pick = st.selectbox("Which wrapped?", choices, key="card_pick")
    if pick == "Lifetime":
        label = "Lifetime"
        songs_n, artists_n = ov["distinct_songs"], ov["distinct_artists"]
        new_line = f"{day_text(ov['first_day'])} to {day_text(ov['last_day'])}"
        best = busiest_days(1).iloc[0]
        stat3 = ("Biggest day", f"{int(best['plays'])} plays, {day_text(best['day'])}")
        t_songs, t_artists, t_album = top_songs(5), top_artists(5), top_albums(1)
        card_plays, card_hours = ov["real_plays"], ov["hours"]
    else:
        yc = year_card(int(pick))
        label = pick
        songs_n, artists_n = yc["songs"], yc["artists"]
        new_line = f"{fmt_int(yc['new_songs'])} songs new to you"
        stat3 = ("Biggest day", f"{yc['busiest_day_plays']} plays, {day_text(yc['busiest_day'])}")
        t_songs, t_artists, t_album = yc["top_songs"], yc["top_artists"], yc["top_album"]
        card_plays, card_hours = yc["plays"], yc["hours"]

    top = t_songs.iloc[0]
    img = covers.get(top["track_id"])
    img_html = f'<img src="{esc(img)}" alt="">' if img else ""
    songs_li = "".join(f"<li>{esc(r.track_name)} <span>{esc(r.artist_name)}</span></li>" for r in t_songs.itertuples())
    artists_li = "".join(f"<li>{esc(r.artist_name)} <span>{fmt_int(r.plays)} plays</span></li>" for r in t_artists.itertuples())
    album_html = (f"<div class='k'>Top album</div><div class='v'>{esc(t_album.iloc[0]['album_name'])}</div>"
                  if len(t_album) else "")
    st.markdown(f"""
<style>
.wcard{{background:linear-gradient(135deg,#0b3d2e 0%,#1DB954 55%,#7be39a 100%);color:#fff;border-radius:20px;padding:28px 32px;
max-width:860px;box-shadow:0 12px 40px rgba(0,0,0,.35);font-family:inherit}}
.wcard h2{{margin:0;font-size:2.6rem;letter-spacing:-.02em;color:#fff}}
.wcard .sub{{opacity:.85;margin-bottom:18px}}
.wcard .big{{display:flex;gap:28px;flex-wrap:wrap;margin:10px 0 22px}}
.wcard .big div{{min-width:120px}}
.wcard .big b{{display:block;font-size:2rem;line-height:1.1}}
.wcard .big span{{opacity:.85;font-size:.85rem}}
.wcard .grid{{display:grid;grid-template-columns:200px 1fr 1fr;gap:24px;align-items:start}}
.wcard img{{width:200px;height:200px;object-fit:cover;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.4)}}
.wcard .top1{{font-weight:700;font-size:1.1rem;margin-top:8px}}
.wcard ol{{margin:6px 0 0;padding-left:20px}} .wcard li{{margin:3px 0}} .wcard li span{{display:block;opacity:.8;font-size:.8rem}}
.wcard .k{{opacity:.8;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;margin-top:14px}}
.wcard .v{{font-weight:600}}
@media(max-width:700px){{.wcard .grid{{grid-template-columns:1fr}}}}
</style>
<div class="wcard">
  <h2>{esc(label)}</h2>
  <div class="sub">{esc(new_line)}</div>
  <div class="big">
    <div><b>{fmt_int(card_hours * 60)}</b><span>minutes listened</span></div>
    <div><b>{fmt_int(card_plays)}</b><span>real plays</span></div>
    <div><b>{fmt_int(songs_n)}</b><span>different songs</span></div>
    <div><b>{fmt_int(artists_n)}</b><span>different artists</span></div>
  </div>
  <div class="grid">
    <div>{img_html}<div class="top1">#1 {esc(top['track_name'])}</div><div>{esc(top['artist_name'])}, {fmt_int(top['plays'])} plays</div></div>
    <div><div class="k">Top songs</div><ol>{songs_li}</ol></div>
    <div><div class="k">Top artists</div><ol>{artists_li}</ol>{album_html}
      <div class="k">{esc(stat3[0])}</div><div class="v">{esc(stat3[1])}</div></div>
  </div>
</div>""", unsafe_allow_html=True)
    st.caption("Take a screenshot to share it.")
