import unittest
from unittest import mock

import lookup

ID = "2F0mHkNH99kPbIh1kKDRga"


class ParseTests(unittest.TestCase):
    def test_accepts_links_uris_and_bare_ids(self):
        self.assertEqual(lookup.parse_track_id(f"https://open.spotify.com/track/{ID}?si=abc"), ID)
        self.assertEqual(lookup.parse_track_id(f"https://open.spotify.com/intl-en/track/{ID}"), ID)
        self.assertEqual(lookup.parse_track_id(f"spotify:track:{ID}"), ID)
        self.assertEqual(lookup.parse_track_id(f"  {ID}  "), ID)

    def test_rejects_other_input(self):
        self.assertIsNone(lookup.parse_track_id(f"https://open.spotify.com/album/{ID}"))
        self.assertIsNone(lookup.parse_track_id("not a link"))
        self.assertIsNone(lookup.parse_track_id(""))
        self.assertIsNone(lookup.parse_track_id(None))


class AudioMoodTests(unittest.TestCase):
    def test_quadrants(self):
        self.assertEqual(lookup.audio_mood(0.8, 0.8), "upbeat")
        self.assertEqual(lookup.audio_mood(0.2, 0.8), "intense")
        self.assertEqual(lookup.audio_mood(0.8, 0.2), "calm")
        self.assertEqual(lookup.audio_mood(0.2, 0.2), "mellow")

    def test_threshold_is_inclusive_and_missing_is_none(self):
        self.assertEqual(lookup.audio_mood(0.5, 0.5), "upbeat")
        self.assertIsNone(lookup.audio_mood(None, 0.5))


class VoteTests(unittest.TestCase):
    SEED = {"ambient": "calm", "indie": "mellow", "rnb": "mellow", "rap": "intense", "india": "unclassified"}

    def test_most_votes_wins_and_unclassified_never_votes(self):
        result = lookup.vote([("india", 100), ("Indie", 80), ("rnb", 60), ("rap", 50)], self.SEED)
        self.assertEqual(result["winner"], "mellow")
        self.assertEqual(result["counts"], {"calm": 0, "mellow": 2, "intense": 1, "upbeat": 0})
        self.assertEqual((result["top"], result["second"]), (2, 1))
        self.assertEqual(result["how"], "clear majority")
        moods = {t["tag"]: t["mood"] for t in result["per_tag"]}
        self.assertEqual(moods, {"india": None, "Indie": "mellow", "rnb": "mellow", "rap": "intense"})

    def test_tie_goes_to_alphabetically_first_mood(self):
        result = lookup.vote([("rap", 90), ("ambient", 80)], self.SEED)
        self.assertEqual(result["winner"], "calm")
        self.assertEqual(result["how"], "tie, broken alphabetically")

    def test_single_tag_decides(self):
        self.assertEqual(lookup.vote([("rap", 90), ("india", 80)], self.SEED)["how"], "one tag decided it")

    def test_light_and_surplus_tags_are_not_used(self):
        light = lookup.vote([("rap", 90), ("ambient", 9)], self.SEED)
        self.assertEqual(light["winner"], "intense")
        self.assertFalse([t for t in light["per_tag"] if t["tag"] == "ambient"][0]["used"])
        many = lookup.vote([("rap", 90)] + [("ambient", 80)] * 5, self.SEED)
        self.assertEqual(sum(t["used"] for t in many["per_tag"]), lookup.MAX_TAGS)

    def test_no_usable_tags(self):
        for tags in ([("india", 90)], []):
            result = lookup.vote(tags, self.SEED)
            self.assertIsNone(result["winner"])
            self.assertEqual(result["how"], "no tag maps to a mood")

    def test_seed_file_loads(self):
        mapping = lookup.load_genre_mood_map()
        self.assertEqual(mapping["ambient"], "calm")
        self.assertEqual(mapping["hip-hop"], "intense")  # lower-cased keys


class LastfmTests(unittest.TestCase):
    def test_missing_key_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {"LASTFM_API_KEY": ""}):
            with self.assertRaises(lookup.LookupFailed):
                lookup.lastfm_artist("Someone")

    def test_artist_parsing_and_not_found_handling(self):
        responses = {
            "artist.gettoptags": {"toptags": {"tag": [{"name": "rap", "count": "100"}, {"name": "indie", "count": 40}]}},
            "artist.getinfo": {"artist": {"name": "Someone", "stats": {"listeners": "1200", "playcount": "9000"},
                               "similar": {"artist": [{"name": "A"}, {"name": "B"}]}}},
        }

        def fake_get(url, params=None, timeout=None):
            resp = mock.Mock()
            resp.json.return_value = responses[params["method"]]
            return resp

        with mock.patch.object(lookup.requests, "get", fake_get):
            out = lookup.lastfm_artist("someone", api_key="k")
        self.assertEqual(out["tags"], [("rap", 100), ("indie", 40)])
        self.assertEqual((out["listeners"], out["playcount"]), (1200, 9000))
        self.assertEqual(out["similar"], ["A", "B"])
        self.assertTrue(out["found"])

        def not_found(url, params=None, timeout=None):
            resp = mock.Mock()
            resp.json.return_value = {"error": 6, "message": "Artist not found"}
            return resp

        with mock.patch.object(lookup.requests, "get", not_found):
            out = lookup.lastfm_artist("nobody", api_key="k")
        self.assertEqual(out["tags"], [])
        self.assertFalse(out["found"])


if __name__ == "__main__":
    unittest.main()
