import unittest

from covers import cover_rows_from_payload, is_allowed_cover_url, pick_cover


class CoverTests(unittest.TestCase):
    def test_only_spotify_image_hosts(self):
        self.assertTrue(is_allowed_cover_url("https://i.scdn.co/image/abc"))
        self.assertTrue(is_allowed_cover_url("https://image-cdn-ak.spotifycdn.com/image/abc"))
        self.assertFalse(is_allowed_cover_url("http://i.scdn.co/image/abc"))
        self.assertFalse(is_allowed_cover_url("https://evil.example.com/i.scdn.co/x"))
        self.assertFalse(is_allowed_cover_url("https://i.scdn.co.evil.com/x"))
        self.assertFalse(is_allowed_cover_url("javascript:alert(1)"))
        self.assertFalse(is_allowed_cover_url(None))

    def test_pick_closest_to_300_and_skip_bad_hosts(self):
        images = [
            {"url": "https://i.scdn.co/image/big", "width": 640},
            {"url": "https://i.scdn.co/image/mid", "width": 300},
            {"url": "https://evil.example.com/x", "width": 300},
        ]
        self.assertEqual(pick_cover(images), "https://i.scdn.co/image/mid")
        self.assertIsNone(pick_cover([{"url": "https://evil.example.com/x", "width": 300}]))
        self.assertIsNone(pick_cover(None))

    def test_payload_rows_dedupe_by_track(self):
        item = {"track": {"id": "A" * 22, "album": {"images": [{"url": "https://i.scdn.co/image/a", "width": 300}]}}}
        self.assertEqual(cover_rows_from_payload([item, item]), [("A" * 22, "https://i.scdn.co/image/a")])


if __name__ == "__main__":
    unittest.main()
