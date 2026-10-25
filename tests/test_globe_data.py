import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import globe_data  # noqa: E402
import wrapped  # noqa: E402


def history(clusters=3, songs_per_cluster=24, sittings=40, seed=1):
    """Plays in sittings: every sitting draws only from one cluster, so the clusters are the "tastes" the map should find."""
    rng = np.random.default_rng(seed)
    rows, t = [], pd.Timestamp("2024-01-01 10:00", tz="Asia/Kolkata")
    for s in range(sittings * clusters):
        c = s % clusters
        for song in rng.choice(songs_per_cluster, size=8, replace=False):
            rows.append((t, f"id{c}_{song}", f"Song {c}-{song}", f"Artist {c}", 200.0))
            t += pd.Timedelta(seconds=210)
        t += pd.Timedelta(hours=3)                     # a long silence ends the sitting
    df = pd.DataFrame(rows, columns=["played_at", "track_id", "track_name", "artist_name", "seconds_played"])
    df["album_name"], df["is_real_play"], df["skipped"] = "album", True, False
    return wrapped.real_plays(wrapped.prepare(df))


REAL = history()


class SongSpaceTests(unittest.TestCase):
    def test_every_song_is_placed_inside_the_map(self):
        space = globe_data.build_song_space(REAL, core_size=60)
        songs = space["songs"]
        self.assertEqual(len(songs), REAL["song_key"].nunique())
        self.assertEqual([s["i"] for s in songs], list(range(len(songs))))
        for s in songs:
            self.assertTrue(0 <= s["x"] <= globe_data.MAP_SIZE and 0 <= s["y"] <= globe_data.MAP_SIZE)
        self.assertEqual(space["years"], [2024])

    def test_songs_from_the_same_sittings_land_closer_together(self):
        songs = globe_data.build_song_space(REAL, core_size=60)["songs"]
        pts = np.array([[s["x"], s["y"]] for s in songs])
        group = np.array([int(s["artist"].split()[-1]) for s in songs])
        d = np.linalg.norm(pts[:, None] - pts[None], axis=2)
        same = d[(group[:, None] == group[None]) & ~np.eye(len(songs), dtype=bool)].mean()
        different = d[group[:, None] != group[None]].mean()
        self.assertLess(same, different * 0.6)

    def test_same_history_gives_the_same_map(self):
        a = globe_data.build_song_space(REAL, core_size=60)["songs"]
        b = globe_data.build_song_space(REAL, core_size=60)["songs"]
        self.assertEqual([(s["x"], s["y"]) for s in a], [(s["x"], s["y"]) for s in b])

    def test_song_fields_and_order(self):
        songs = globe_data.build_song_space(REAL, core_size=60)["songs"]
        plays = [s["plays"] for s in songs]
        self.assertEqual(plays, sorted(plays, reverse=True))          # most played first
        s = songs[0]
        self.assertEqual(sum(s["yr"]), s["plays"])
        self.assertEqual((s["first"], s["last"]), (2024, 2024))
        self.assertTrue(s["id"].startswith("id") and s["name"].startswith("Song"))

    def test_too_little_history_is_reported(self):
        tiny = REAL[REAL["song_key"].isin(REAL["song_key"].unique()[:20])]
        self.assertEqual(globe_data.build_song_space(tiny)["songs"], [])
        self.assertEqual(globe_data.build_song_space(tiny)["reason"], "few")


if __name__ == "__main__":
    unittest.main()
