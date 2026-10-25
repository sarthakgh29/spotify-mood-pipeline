"""Lifetime-wrapped analysis of listening history. Pure pandas functions, no Streamlit, so they can be tested.

Input is a DataFrame of plays with columns: played_at, track_id, track_name, artist_name, album_name,
seconds_played, is_real_play, skipped. A "real play" is a play of 30 seconds or more.
Songs are merged by title and artist, so a song released twice counts once.
Everything is in IST.
"""
import pandas as pd

TZ = "Asia/Kolkata"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BANDS = [("Night (12am-6am)", 0, 6), ("Morning (6am-12pm)", 6, 12),
         ("Afternoon (12pm-5pm)", 12, 17), ("Evening (5pm-12am)", 17, 24)]


def prepare(df):
    """Add the columns every other function relies on."""
    d = df.copy()
    d["played_at"] = pd.to_datetime(d["played_at"], utc=True).dt.tz_convert(TZ)
    local = d["played_at"].dt.tz_localize(None)
    d["day"] = local.dt.normalize()
    d["year"] = d["played_at"].dt.year
    d["month"] = d["played_at"].dt.month
    d["hour"] = d["played_at"].dt.hour
    d["weekday"] = d["played_at"].dt.weekday
    d["hours"] = d["seconds_played"].fillna(0) / 3600.0
    d["song_key"] = d["track_name"].fillna("").str.casefold() + "|" + d["artist_name"].fillna("").str.casefold()
    return d


def real_plays(d):
    return d[d["is_real_play"]]


def _songs(real):
    """One row per song (merged by title and artist), with the most-played track id as its representative."""
    if real.empty:
        return pd.DataFrame(columns=["song_key", "track_id", "track_name", "artist_name", "album_name", "plays", "hours"])
    g = (real.groupby(["song_key", "track_id", "track_name", "artist_name", "album_name"], dropna=False)
             .agg(plays=("track_id", "size"), hours=("hours", "sum")).reset_index())
    g = g.sort_values(["song_key", "plays"], ascending=[True, False])
    rep = g.drop_duplicates("song_key")[["song_key", "track_id", "track_name", "artist_name", "album_name"]]
    tot = g.groupby("song_key").agg(plays=("plays", "sum"), hours=("hours", "sum")).reset_index()
    return rep.merge(tot, on="song_key").sort_values(["plays", "hours"], ascending=False).reset_index(drop=True)


def _slice(real, year=None, month=None):
    if year is not None:
        real = real[real["year"] == year]
    if month is not None:
        real = real[real["month"] == month]
    return real


def top_songs(real, n=20, year=None, month=None):
    return _songs(_slice(real, year, month)).head(n)


def top_artists(real, n=20, year=None, month=None):
    r = _slice(real, year, month)
    if r.empty:
        return pd.DataFrame(columns=["artist_name", "plays", "hours", "songs"])
    g = r.groupby("artist_name").agg(plays=("track_id", "size"), hours=("hours", "sum"), songs=("song_key", "nunique"))
    return g.sort_values(["plays", "hours"], ascending=False).head(n).reset_index()


def top_albums(real, n=10, year=None):
    r = _slice(real, year).dropna(subset=["album_name"])
    if r.empty:
        return pd.DataFrame(columns=["album_name", "artist_name", "plays"])
    g = r.groupby(["album_name", "artist_name"]).size().rename("plays").reset_index()
    return g.sort_values("plays", ascending=False).head(n).reset_index(drop=True)


def overview(real, all_plays):
    days = real["day"].nunique()
    return {
        "real_plays": int(len(real)),
        "all_plays": int(len(all_plays)),
        "hours": float(real["hours"].sum()),
        "distinct_songs": int(real["song_key"].nunique()),
        "distinct_artists": int(real["artist_name"].nunique()),
        "first_day": real["day"].min(),
        "last_day": real["day"].max(),
        "active_days": int(days),
        "plays_per_active_day": float(len(real) / days) if days else 0.0,
    }


def by_year(real):
    if real.empty:
        return pd.DataFrame(columns=["year", "plays", "hours", "songs", "artists"])
    return (real.groupby("year").agg(plays=("track_id", "size"), hours=("hours", "sum"),
                                     songs=("song_key", "nunique"), artists=("artist_name", "nunique"))
                .reset_index())


def by_month(real, year):
    r = real[real["year"] == year]
    m = r.groupby("month").agg(plays=("track_id", "size"), hours=("hours", "sum")).reindex(range(1, 13), fill_value=0)
    m.index.name = "month"
    return m.reset_index()


def monthly_rulers(real, year):
    """For each month of a year, the song with the most real plays, and its share of that month."""
    rows = []
    r = real[real["year"] == year]
    for month, chunk in r.groupby("month"):
        songs = _songs(chunk)
        top = songs.iloc[0]
        rows.append({"month": int(month), "track_id": top["track_id"], "track_name": top["track_name"],
                     "artist_name": top["artist_name"], "album_name": top["album_name"],
                     "plays": int(top["plays"]), "month_plays": int(len(chunk)),
                     "share": float(top["plays"] / len(chunk))})
    return pd.DataFrame(rows)


def hour_weekday(real):
    m = real.groupby(["weekday", "hour"]).size().unstack(fill_value=0)
    return m.reindex(index=range(7), columns=range(24), fill_value=0)


def time_bands(real):
    total = max(len(real), 1)
    return pd.DataFrame([{"band": name, "plays": int(((real["hour"] >= lo) & (real["hour"] < hi)).sum()),
                          "share": float(((real["hour"] >= lo) & (real["hour"] < hi)).sum() / total)}
                         for name, lo, hi in BANDS])


def daily_counts(real, year):
    r = real[real["year"] == year]
    return r.groupby("day").size()


def streaks(real):
    """Longest run of days in a row with a real play, and the longest silence between two listening days."""
    days = pd.Series(sorted(real["day"].unique()))
    if days.empty:
        return {"streak_days": 0, "streak_start": None, "streak_end": None, "gap_days": 0, "gap_start": None, "gap_end": None}
    gaps = days.diff().dt.days.fillna(1).astype(int)
    run_id = (gaps != 1).cumsum()
    runs = days.groupby(run_id).agg(["min", "max", "count"])
    best = runs.sort_values("count", ascending=False).iloc[0]
    big = gaps.idxmax()
    gap_days = int(gaps.max()) - 1 if len(days) > 1 else 0
    return {"streak_days": int(best["count"]), "streak_start": best["min"], "streak_end": best["max"],
            "gap_days": max(gap_days, 0),
            "gap_start": days[big - 1] + pd.Timedelta(days=1) if big > 0 and gap_days > 0 else None,
            "gap_end": days[big] - pd.Timedelta(days=1) if big > 0 and gap_days > 0 else None}


def busiest_days(real, n=10):
    g = real.groupby("day").agg(plays=("track_id", "size"), hours=("hours", "sum"))
    return g.sort_values(["plays", "hours"], ascending=False).head(n).reset_index()


def milestones(real, marks=(1, 1000, 10000, 50000, 100000, 150000)):
    r = real.sort_values("played_at").reset_index(drop=True)
    out = []
    for k in marks:
        if k <= len(r):
            row = r.iloc[k - 1]
            out.append({"play_number": k, "when": row["played_at"], "track_id": row["track_id"],
                        "track_name": row["track_name"], "artist_name": row["artist_name"], "album_name": row["album_name"]})
    return pd.DataFrame(out)


def skip_rates(all_plays):
    """Per year: how many plays, how many were real (30s+), and how many Spotify flagged as skipped."""
    g = all_plays.groupby("year").agg(plays=("track_id", "size"), real=("is_real_play", "sum"), skipped=("skipped", "sum"))
    g["share_real"] = g["real"] / g["plays"]
    g["share_skipped"] = g["skipped"] / g["plays"]
    return g.reset_index()


def discovery(real):
    """Per year: songs heard for the first time that year, and the share of that year's plays they account for."""
    first = real.groupby("song_key")["year"].min().rename("first_year")
    r = real.join(first, on="song_key")
    rows = []
    for year, chunk in r.groupby("year"):
        new = chunk[chunk["first_year"] == year]
        rows.append({"year": int(year), "new_songs": int(new["song_key"].nunique()),
                     "plays": int(len(chunk)), "plays_of_new": int(len(new)),
                     "share_new": float(len(new) / len(chunk))})
    return pd.DataFrame(rows)


def comfort_songs(real, min_years=5, n=25):
    """Songs you came back to in many different years."""
    g = real.groupby("song_key").agg(years=("year", "nunique"), plays=("track_id", "size"),
                                     first_year=("year", "min"), last_year=("year", "max"))
    g = g[g["years"] >= min_years].sort_values(["years", "plays"], ascending=False).head(n).reset_index()
    return g.merge(_songs(real)[["song_key", "track_id", "track_name", "artist_name", "album_name"]], on="song_key")


def forgotten_favourites(real, min_plays=20, quiet_days=365, as_of=None, n=40):
    """Songs you played a lot, but not at all in the last `quiet_days` days."""
    as_of = pd.Timestamp(as_of if as_of is not None else real["day"].max())
    g = real.groupby("song_key").agg(plays=("track_id", "size"), last_day=("day", "max"), first_day=("day", "min"))
    peak = (real.groupby(["song_key", "year"]).size().rename("n").reset_index()
                .sort_values(["song_key", "n"], ascending=[True, False]).drop_duplicates("song_key")
                .set_index("song_key").rename(columns={"year": "peak_year", "n": "peak_year_plays"}))
    g = g.join(peak)
    g = g[(g["plays"] >= min_plays) & (g["last_day"] < as_of - pd.Timedelta(days=quiet_days))]
    g["quiet_days"] = (as_of - g["last_day"]).dt.days
    g = g.sort_values("plays", ascending=False).head(n).reset_index()
    return g.merge(_songs(real)[["song_key", "track_id", "track_name", "artist_name", "album_name"]], on="song_key")


def obsessions(real, n=15):
    """The most plays of one song in a single day."""
    g = real.groupby(["song_key", "day"]).size().rename("plays_that_day").reset_index()
    g = g.sort_values(["plays_that_day", "day"], ascending=[False, True]).drop_duplicates("song_key").head(n)
    return g.merge(_songs(real)[["song_key", "track_id", "track_name", "artist_name", "album_name"]], on="song_key")


def artist_by_year(real, top=8):
    """Plays per year for the artists who are in the overall top list, for a stacked chart."""
    names = top_artists(real, top)["artist_name"].tolist()
    g = real[real["artist_name"].isin(names)].groupby(["year", "artist_name"]).size().rename("plays").reset_index()
    return g, names


def yearly_top_artist(real):
    g = real.groupby(["year", "artist_name"]).size().rename("plays").reset_index()
    g = g.sort_values(["year", "plays"], ascending=[True, False]).drop_duplicates("year")
    return g.reset_index(drop=True)


def year_card(real, all_plays, year):
    """Everything for one year's wrapped card."""
    r = real[real["year"] == year]
    if r.empty:
        return None
    first_ever = real.groupby("song_key")["year"].min()
    new_songs = int((first_ever == year).sum())
    months = by_month(real, year)
    busiest = busiest_days(r, 1).iloc[0]
    st = streaks(r)
    return {
        "year": year,
        "plays": int(len(r)),
        "hours": float(r["hours"].sum()),
        "songs": int(r["song_key"].nunique()),
        "artists": int(r["artist_name"].nunique()),
        "new_songs": new_songs,
        "top_songs": top_songs(real, 5, year),
        "top_artists": top_artists(real, 5, year),
        "top_album": top_albums(real, 1, year),
        "best_month": int(months.sort_values("plays", ascending=False).iloc[0]["month"]),
        "busiest_day": busiest["day"], "busiest_day_plays": int(busiest["plays"]),
        "streak_days": st["streak_days"],
    }


# ------------------------------------------------------------------ lookups (one artist, one song)
def artist_options(real):
    """Artists by real plays, most played first: (artist_name, plays)."""
    return real.groupby("artist_name").size().sort_values(ascending=False)


def song_options(real):
    """One row per song (merged by title and artist), most played first."""
    return _songs(real)


def monthly_counts(subset, real):
    """Real plays per calendar month for `subset`, over the whole history's month range (zeros filled in)."""
    months = pd.period_range(real["day"].min(), real["day"].max(), freq="M")
    if subset.empty:
        return pd.Series(0, index=months)
    s = subset.groupby(subset["day"].dt.to_period("M")).size()
    return s.reindex(months, fill_value=0)


def peak_window(counts, width=3):
    """The `width` consecutive months with the most plays: (first month, last month, plays, share of all)."""
    if counts.sum() == 0:
        return None
    roll = counts.rolling(width, min_periods=1).sum()
    end = roll.idxmax()
    start = max(end - (width - 1), counts.index[0])
    return start, end, int(roll.max()), float(roll.max() / counts.sum())


def _lookup_core(sub, real):
    counts = monthly_counts(sub, real)
    daily = sub.groupby("day").size()
    top_day = daily.sort_values(ascending=False).head(1)
    return {
        "plays": int(len(sub)), "hours": float(sub["hours"].sum()),
        "first_day": sub["day"].min(), "last_day": sub["day"].max(),
        "active_days": int(daily.size),
        "monthly": counts, "yearly": sub.groupby("year").size(),
        "peak_month": counts.idxmax(), "peak_month_plays": int(counts.max()),
        "peak_window": peak_window(counts),
        "peak_day": top_day.index[0], "peak_day_plays": int(top_day.iloc[0]),
        "hour_share": sub.groupby("hour").size().reindex(range(24), fill_value=0) / len(sub),
    }


def artist_lookup(real, artist):
    """Everything about one artist's real plays, or None if there are none."""
    sub = real[real["artist_name"] == artist]
    if sub.empty:
        return None
    out = _lookup_core(sub, real)
    out["songs"] = int(sub["song_key"].nunique())
    out["top_songs"] = _songs(sub).head(100)
    return out


def song_lookup(real, song_key):
    """Everything about one song's real plays (all its releases merged), or None."""
    sub = real[real["song_key"] == song_key]
    if sub.empty:
        return None
    out = _lookup_core(sub, real)
    out["song"] = _songs(sub).iloc[0]
    return out
