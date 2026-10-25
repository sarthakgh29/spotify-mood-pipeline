import io
import os
import sys
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import card_image  # noqa: E402

CARD = {
    "label": "Lifetime", "sub": "01 Apr 2020 to 18 Oct 2026", "minutes": 146878, "plays": 56492, "songs": 3500, "artists": 1314,
    "top": {"name": "To The Souls That Leave Us Too Soon", "artist": "Doug Clark", "plays": 694},
    "top_songs": [("To The Souls That Leave Us Too Soon", "Doug Clark"), ("Paro", "Aditya Rikhari"), ("comethru", "Jeremy Zucker"),
                  ("Nothing", "Bruno Major"), ("Chaand Baaliyan", "Aditya A")],
    "top_artists": [("Karan Aujla", 3335), ("BoyWithUke", 2789), ("Diljit Dosanjh", 2210), ("AP Dhillon", 2139), ("Aditya Rikhari", 1496)],
}


def png(card=CARD, cover=None):
    return card_image.build_card_png(card, cover)


def some_cover():
    im = Image.new("RGB", (300, 300), (200, 30, 30))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


class CardImageTests(unittest.TestCase):
    def test_is_a_1080_by_1350_png(self):
        data = png()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        im = Image.open(io.BytesIO(data))
        self.assertEqual(im.size, (1080, 1350))

    def test_same_card_gives_the_same_image(self):
        self.assertEqual(png(), png())

    def test_background_runs_dark_green_to_light_green(self):
        px = Image.open(io.BytesIO(png())).convert("RGB")
        dark, light = px.getpixel((2, 2)), px.getpixel((1077, 1347))
        self.assertLess(sum(dark), sum(light))
        self.assertGreater(light[1], light[0])                           # green dominates at the light end

    def test_cover_is_drawn_when_given_and_changes_the_card(self):
        with_cover = Image.open(io.BytesIO(png(cover=some_cover()))).convert("RGB")
        self.assertNotEqual(png(), png(cover=some_cover()))
        r, g, b = with_cover.getpixel((890, 800))                         # middle of the cover square
        self.assertGreater(r, 150)
        self.assertLess(g, 80)

    def test_a_broken_cover_does_not_stop_the_card(self):
        self.assertEqual(png(cover=b"not an image"), png())

    def test_long_and_non_latin_titles_are_fine(self):
        card = dict(CARD, top={"name": "x" * 400, "artist": "y" * 300, "plays": 3},
                    top_songs=[("夜に駆ける" * 30, "YOASOBI"), ("मेरे रश्के क़मर", "Nusrat"), ("안녕하세요" * 20, "아티스트"), ("a", "b"), ("c", "d")])
        Image.open(io.BytesIO(png(card))).load()                         # drawing finished and the PNG is valid

    def test_clip_always_ends_and_fits(self):
        im = Image.new("RGBA", (10, 10))
        d = ImageDraw.Draw(im)
        short = card_image.clip(d, "Paro", 500, 30, 600)
        self.assertEqual(short, "Paro")
        long = card_image.clip(d, "very long title " * 40, 300, 30, 600)
        self.assertTrue(long.endswith("..."))
        self.assertLessEqual(d.textlength(long, font=card_image.font_for(long, 30, 600)), 300)
        self.assertTrue(card_image.clip(d, "x" * 500, 1, 30, 600).endswith("..."))   # even a width nothing fits in

    def test_only_spotify_image_hosts_are_fetched(self):
        self.assertIsNone(card_image.fetch_cover_bytes("https://example.com/cover.jpg"))
        self.assertIsNone(card_image.fetch_cover_bytes("http://i.scdn.co/image/abc"))     # not https
        self.assertIsNone(card_image.fetch_cover_bytes(None))


if __name__ == "__main__":
    unittest.main()
