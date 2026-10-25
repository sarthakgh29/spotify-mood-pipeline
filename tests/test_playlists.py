import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import playlists  # noqa: E402

A, B, C = "a" * 22, "b" * 22, "c" * 22


class FakeSpotify:
    def __init__(self):
        self.created, self.added = [], []

    def current_user_playlist_create(self, name, public, description):
        self.created.append(("me", name, public, description))
        return {"id": "PL1", "external_urls": {"spotify": "https://open.spotify.com/playlist/PL1"}}

    def playlist_add_items(self, pid, uris):
        self.added.append((pid, list(uris)))


class ResolveSpotify:
    """track() says which ids are dead; search() returns one playable copy for known songs."""
    def __init__(self, dead, found):
        self.dead, self.found = dead, found

    def track(self, tid, market=None):
        return {"name": "", "is_playable": False} if tid in self.dead else {"name": "x", "is_playable": True}

    def search(self, q, type, limit, market):
        title = q.split("track:")[1].split(" artist:")[0]
        hit = self.found.get(title)
        return {"tracks": {"items": [hit] if hit else []}}


def copy(tid, name, artists, playable=True):
    return {"id": tid, "name": name, "artists": [{"name": a} for a in artists], "is_playable": playable}


class ResolveTests(unittest.TestCase):
    def test_dead_ids_are_swapped_for_a_playable_copy_and_unfindable_ones_reported(self):
        sp = ResolveSpotify(dead={A, C}, found={"Wo Ladki": copy(B, "Wo Ladki", ["Amit Trivedi", "Arijit Singh"])})
        tracks = [{"track_id": A, "track_name": "Wo Ladki", "artist_name": "Arijit Singh"},
                  {"track_id": "d" * 22, "track_name": "Fine", "artist_name": "Arijit Singh"},
                  {"track_id": C, "track_name": "Gone", "artist_name": "Arijit Singh"}]
        ids, missing = playlists.resolve_playable(sp, tracks)
        self.assertEqual(ids, [B, "d" * 22])
        self.assertEqual(missing, ["Gone"])

    def test_search_match_needs_the_artist_and_ignores_unplayable_copies(self):
        sp = ResolveSpotify(dead=set(), found={})
        sp.search = lambda q, type, limit, market: {"tracks": {"items": [
            copy(A, "Song", ["Someone Else"]), copy(B, "Song", ["Arijit Singh"], playable=False),
            copy(C, 'Song (From "Film")', ["Arijit Singh"])]}}
        self.assertEqual(playlists.find_playable_copy(sp, "Song", "Arijit Singh"), C)

    def test_duplicate_results_are_added_once(self):
        sp = ResolveSpotify(dead={A}, found={"Same": copy(B, "Same", ["X"])})
        tracks = [{"track_id": A, "track_name": "Same", "artist_name": "X"},
                  {"track_id": B, "track_name": "Same", "artist_name": "X"}]
        self.assertEqual(playlists.resolve_playable(sp, tracks)[0], [B])


class PlaylistTests(unittest.TestCase):
    def test_track_uris_drop_bad_and_duplicate_ids(self):
        self.assertEqual(playlists.track_uris([A, "short", A, None, B]), [f"spotify:track:{A}", f"spotify:track:{B}"])

    def test_create_is_private_by_default_and_reports_count(self):
        sp = FakeSpotify()
        r = playlists.create_playlist(sp, "  My   mix ", [A, B, C])
        self.assertEqual(sp.created[0][1:3], ("My mix", False))
        self.assertEqual(r["added"], 3)
        self.assertEqual(r["url"], "https://open.spotify.com/playlist/PL1")

    def test_adds_in_batches_of_100(self):
        sp = FakeSpotify()
        ids = [f"{i:022d}" for i in range(250)]
        playlists.create_playlist(sp, "big", ids)
        self.assertEqual([len(u) for _, u in sp.added], [100, 100, 50])

    def test_rejects_empty_name_or_tracks(self):
        with self.assertRaises(ValueError):
            playlists.create_playlist(FakeSpotify(), "  ", [A])
        with self.assertRaises(ValueError):
            playlists.create_playlist(FakeSpotify(), "x", ["bad"])
        sp = FakeSpotify()
        with self.assertRaises(ValueError):
            playlists.create_playlist(sp, "x", [])
        self.assertEqual(sp.created, [])


if __name__ == "__main__":
    unittest.main()
