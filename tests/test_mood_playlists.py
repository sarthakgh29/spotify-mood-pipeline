import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mood_playlists  # noqa: E402


def row(i, name, artist, plays):
    return {"track_id": i, "track_name": name, "artist_name": artist, "real_plays": plays}


class PickSongsTests(unittest.TestCase):
    def test_most_played_first_and_capped(self):
        rows = [row("a", "A", "x", 5), row("b", "B", "x", 9), row("c", "C", "x", 7)]
        self.assertEqual([r["track_id"] for r in mood_playlists.pick_songs(rows, max_songs=2)], ["b", "c"])

    def test_songs_below_min_plays_are_left_out(self):
        rows = [row("a", "A", "x", 1), row("b", "B", "x", 2)]
        self.assertEqual([r["track_id"] for r in mood_playlists.pick_songs(rows, min_plays=2)], ["b"])

    def test_same_song_on_two_ids_counts_once(self):
        rows = [row("a", "Paro", "Aditya Rikhari", 5), row("b", "paro!", "aditya rikhari", 9)]
        self.assertEqual([r["track_id"] for r in mood_playlists.pick_songs(rows)], ["b"])


if __name__ == "__main__":
    unittest.main()
