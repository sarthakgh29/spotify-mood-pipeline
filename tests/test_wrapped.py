import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wrapped  # noqa: E402


def plays(rows):
    """rows: (iso time in IST, track_id, track, artist, seconds, skipped)"""
    df = pd.DataFrame(rows, columns=["played_at", "track_id", "track_name", "artist_name", "seconds_played", "skipped"])
    df["played_at"] = pd.to_datetime(df["played_at"]).dt.tz_localize("Asia/Kolkata")
    df["album_name"] = "album " + df["track_name"]
    df["is_real_play"] = df["seconds_played"] >= 30
    return wrapped.prepare(df)


SAMPLE = plays([
    ("2022-01-01 10:00", "t1", "Alpha", "A", 200, False),
    ("2022-01-02 10:00", "t1", "Alpha", "A", 200, False),
    ("2022-01-02 11:00", "t2", "Beta", "B", 10, True),     # too short, not real
    ("2022-02-03 23:30", "t3", "Gamma", "B", 180, False),
    ("2022-02-04 00:10", "t3", "Gamma", "B", 180, False),
    ("2023-03-05 08:00", "t1x", "alpha", "a", 200, False),  # same song re-released: merged by title and artist
    ("2023-03-06 08:00", "t4", "Delta", "C", 120, False),
    ("2023-03-07 08:00", "t4", "Delta", "C", 120, False),
    ("2023-03-07 09:00", "t4", "Delta", "C", 120, False),
])
REAL = wrapped.real_plays(SAMPLE)


class CoreTests(unittest.TestCase):
    def test_real_plays_exclude_short_ones(self):
        self.assertEqual(len(SAMPLE), 9)
        self.assertEqual(len(REAL), 8)

    def test_songs_are_merged_by_title_and_artist(self):
        top = wrapped.top_songs(REAL, 5)
        alpha = top[top["song_key"] == "alpha|a"].iloc[0]
        self.assertEqual(alpha["plays"], 3)                  # 2 in 2022 + 1 re-release in 2023
        self.assertEqual(alpha["track_id"], "t1")            # most-played release represents the song
        self.assertEqual(REAL["song_key"].nunique(), 3)      # Alpha, Gamma, Delta; Beta was too short

    def test_overview_and_years(self):
        o = wrapped.overview(REAL, SAMPLE)
        # artists are counted by exact name, so "A" and the re-release's "a" are two; songs are merged
        self.assertEqual((o["real_plays"], o["all_plays"], o["distinct_songs"], o["distinct_artists"]), (8, 9, 3, 4))
        y = wrapped.by_year(REAL).set_index("year")
        self.assertEqual((y.loc[2022, "plays"], y.loc[2023, "plays"]), (4, 4))

    def test_monthly_rulers(self):
        r = wrapped.monthly_rulers(REAL, 2022).set_index("month")
        self.assertEqual(r.loc[1, "track_name"], "Alpha")
        self.assertEqual(r.loc[1, "plays"], 2)
        self.assertAlmostEqual(r.loc[1, "share"], 1.0)       # the short Beta play is not a real play
        self.assertEqual(set(r.index), {1, 2})

    def test_top_artists_and_albums(self):
        a = wrapped.top_artists(REAL, 5).set_index("artist_name")
        self.assertEqual(a.loc["B", "plays"], 2)
        self.assertEqual(wrapped.top_albums(REAL, 1).iloc[0]["plays"], 3)


class HabitTests(unittest.TestCase):
    def test_streaks(self):
        s = wrapped.streaks(REAL)
        # real-play days: Jan 1, Jan 2, Feb 3, Feb 4, Mar 5, Mar 6, Mar 7
        self.assertEqual(s["streak_days"], 3)
        self.assertEqual(str(s["streak_start"].date()), "2023-03-05")
        self.assertEqual(s["gap_days"], 393)                 # silent from 2022-02-05 to 2023-03-04
        self.assertEqual(str(s["gap_start"].date()), "2022-02-05")
        self.assertEqual(str(s["gap_end"].date()), "2023-03-04")

    def test_time_bands_cover_every_play(self):
        b = wrapped.time_bands(REAL)
        self.assertEqual(b["plays"].sum(), len(REAL))
        self.assertAlmostEqual(b["share"].sum(), 1.0)

    def test_hour_weekday_shape(self):
        m = wrapped.hour_weekday(REAL)
        self.assertEqual(m.shape, (7, 24))
        self.assertEqual(int(m.values.sum()), len(REAL))

    def test_skip_rates(self):
        s = wrapped.skip_rates(SAMPLE).set_index("year")
        self.assertAlmostEqual(s.loc[2022, "share_real"], 4 / 5)

    def test_discovery(self):
        d = wrapped.discovery(REAL).set_index("year")
        self.assertEqual(d.loc[2022, "new_songs"], 2)        # Alpha and Gamma
        self.assertEqual(d.loc[2023, "new_songs"], 1)        # Delta; the Alpha re-release is not new
        self.assertAlmostEqual(d.loc[2023, "share_new"], 3 / 4)

    def test_milestones(self):
        m = wrapped.milestones(REAL, marks=(1, 5, 100))
        self.assertEqual(list(m["play_number"]), [1, 5])
        self.assertEqual(m.iloc[0]["track_name"], "Alpha")

    def test_obsessions_and_busiest_day(self):
        o = wrapped.obsessions(REAL, 1).iloc[0]
        self.assertEqual((o["track_name"], o["plays_that_day"]), ("Delta", 2))
        self.assertEqual(wrapped.busiest_days(REAL, 1).iloc[0]["plays"], 2)


class FavouriteTests(unittest.TestCase):
    def test_comfort_songs_need_several_years(self):
        c = wrapped.comfort_songs(REAL, min_years=2)
        self.assertEqual(list(c["song_key"]), ["alpha|a"])   # Alpha in 2022 and 2023

    def test_forgotten_favourites(self):
        f = wrapped.forgotten_favourites(REAL, min_plays=2, quiet_days=30, as_of="2023-03-07")
        self.assertEqual(list(f["song_key"]), ["gamma|b"])   # Gamma: 2 plays, last in Feb 2022
        self.assertGreater(f.iloc[0]["quiet_days"], 30)
        self.assertEqual(f.iloc[0]["peak_year"], 2022)

    def test_year_card(self):
        card = wrapped.year_card(REAL, SAMPLE, 2022)
        self.assertEqual((card["plays"], card["songs"], card["new_songs"]), (4, 2, 2))
        self.assertEqual(card["top_songs"].iloc[0]["track_name"], "Alpha")
        self.assertIsNone(wrapped.year_card(REAL, SAMPLE, 1999))


class LookupTests(unittest.TestCase):
    def test_song_lookup_merges_releases(self):
        r = wrapped.song_lookup(REAL, "alpha|a")
        self.assertEqual(r["plays"], 3)
        self.assertEqual(str(r["first_day"].date()), "2022-01-01")
        self.assertEqual(str(r["last_day"].date()), "2023-03-05")
        self.assertEqual(r["peak_month_plays"], 2)
        self.assertEqual(str(r["peak_month"]), "2022-01")
        self.assertEqual(r["peak_day_plays"], 1)
        self.assertEqual(int(r["monthly"].sum()), 3)

    def test_artist_lookup(self):
        r = wrapped.artist_lookup(REAL, "B")
        self.assertEqual((r["plays"], r["songs"]), (2, 1))
        self.assertEqual(r["top_songs"].iloc[0]["track_name"], "Gamma")
        self.assertEqual(r["peak_window"][2], 2)
        self.assertAlmostEqual(r["peak_window"][3], 1.0)
        self.assertIsNone(wrapped.artist_lookup(REAL, "nobody"))

    def test_monthly_counts_cover_whole_history(self):
        c = wrapped.monthly_counts(REAL[REAL["artist_name"] == "B"], REAL)
        self.assertEqual(len(c), 15)          # Jan 2022 .. Mar 2023
        self.assertEqual(int(c.sum()), 2)


if __name__ == "__main__":
    unittest.main()
