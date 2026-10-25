import json
import unittest
from unittest import mock

import ai_labeler as ai

TRACK = {
    "track_id": "T1", "track_name": "Some Song", "artist_names": "An Artist, Guest", "album_name": "An Album",
    "tags": ["rnb", "indie"], "valence": 0.31, "energy": 0.72, "danceability": 0.5, "acousticness": 0.1,
    "speechiness": 0.05, "loudness": -6.2, "tempo": 118.0,
}
GOOD = json.dumps({"mood": "intense", "confidence": "high", "reason": "Driving and dark."})


class FakeApiError(Exception):
    def __init__(self, code):
        super().__init__(f"error {code}")
        self.code = code


class PromptTests(unittest.TestCase):
    def test_hybrid_includes_tags_and_numbers(self):
        p = ai.build_prompt(TRACK, "hybrid")
        self.assertIn("Some Song", p)
        self.assertIn("rnb, indie", p)
        self.assertIn("valence: 0.31", p)
        self.assertIn("tempo: 118.00", p)

    def test_text_only_leaves_the_numbers_out(self):
        p = ai.build_prompt(TRACK, "text_only")
        self.assertIn("rnb, indie", p)
        self.assertNotIn("valence", p)
        self.assertNotIn("Audio ratings", p)

    def test_missing_numbers_and_tags_are_handled(self):
        bare = {"track_id": "T2", "track_name": "X", "artist_names": "Y", "album_name": None, "tags": None,
                "valence": None, "energy": float("nan")}
        p = ai.build_prompt(bare, "hybrid")
        self.assertIn("none", p)
        self.assertIn("not available", p)
        self.assertNotIn("nan", p)

    def test_only_metadata_is_sent(self):
        p = ai.build_prompt(TRACK, "hybrid")
        self.assertNotIn("T1", p)  # the track id is not part of the prompt

    def test_unknown_variant(self):
        with self.assertRaises(ValueError):
            ai.build_prompt(TRACK, "nope")


class NotesVariantTests(unittest.TestCase):
    NOTED = dict(TRACK, note="pre-gym hype, dark and confident")

    def test_rule_is_in_every_prompt(self):
        for variant in ai.VARIANTS:
            self.assertIn("not the occasion", ai.build_prompt(self.NOTED, variant))

    def test_description_only_reaches_the_with_notes_variant(self):
        self.assertIn("pre-gym hype", ai.build_prompt(self.NOTED, "with_notes"))
        self.assertNotIn("pre-gym hype", ai.build_prompt(self.NOTED, "hybrid"))
        self.assertNotIn("pre-gym hype", ai.build_prompt(self.NOTED, "text_only"))

    def test_with_notes_also_carries_the_audio_numbers_and_tags(self):
        p = ai.build_prompt(self.NOTED, "with_notes")
        self.assertIn("valence: 0.31", p)
        self.assertIn("rnb, indie", p)

    def test_with_notes_needs_a_description(self):
        for track in (TRACK, dict(TRACK, note=""), dict(TRACK, note="   \n ")):
            with self.assertRaises(ValueError):
                ai.build_prompt(track, "with_notes")

    def test_description_is_one_line_and_capped(self):
        messy = "line one\n\nline   two " + "x" * 2000
        cleaned = ai.clean_note(messy)
        self.assertNotIn("\n", cleaned)
        self.assertTrue(cleaned.startswith("line one line two"))
        self.assertEqual(len(cleaned), ai.NOTE_MAX_CHARS)
        self.assertEqual(ai.clean_note(None), "")

    def test_variants_have_distinct_versions_ending_as_the_sql_expects(self):
        self.assertEqual(len(set(ai.VARIANTS.values())), 3)
        ends = {"hybrid": "hybrid", "text_only": "text", "with_notes": "notes"}
        for variant, version in ai.VARIANTS.items():
            self.assertTrue(version.endswith(ends[variant]), (variant, version))


class ParseTests(unittest.TestCase):
    def test_valid(self):
        a = ai.parse_answer(GOOD)
        self.assertEqual((a.mood, a.confidence), ("intense", "high"))

    def test_rejects_unknown_mood_confidence_and_non_json(self):
        for bad in (
            json.dumps({"mood": "happy", "confidence": "high", "reason": "x"}),
            json.dumps({"mood": "calm", "confidence": "certain", "reason": "x"}),
            json.dumps({"mood": "calm"}),
            "Sure! The mood is calm.",
            "",
        ):
            with self.assertRaises(ValueError):
                ai.parse_answer(bad)

    def test_long_reason_is_trimmed(self):
        text = json.dumps({"mood": "calm", "confidence": "low", "reason": "x" * 1000})
        self.assertEqual(len(ai.parse_answer(text).reason), ai.MAX_REASON_CHARS)


class PendingTests(unittest.TestCase):
    def test_skips_done_keeps_order_and_limits(self):
        tracks = [{"track_id": i} for i in "abcde"]
        self.assertEqual([t["track_id"] for t in ai.select_pending(tracks, {"b", "d"})], ["a", "c", "e"])
        self.assertEqual([t["track_id"] for t in ai.select_pending(tracks, {"b"}, limit=2)], ["a", "c"])
        self.assertEqual(ai.select_pending(tracks, set(tracks and "abcde")), [])


class LabelTrackTests(unittest.TestCase):
    def test_returns_answer(self):
        self.assertEqual(ai.label_track(TRACK, "hybrid", lambda prompt: GOOD).mood, "intense")

    def test_one_retry_on_a_bad_answer_then_gives_up(self):
        replies = iter(["not json", GOOD])
        self.assertEqual(ai.label_track(TRACK, "hybrid", lambda p: next(replies)).mood, "intense")
        self.assertIsNone(ai.label_track(TRACK, "hybrid", lambda p: "still not json"))

    def test_backs_off_on_rate_limit_then_succeeds(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                raise FakeApiError(429)
            return GOOD

        waits = []
        out = ai.label_track(TRACK, "hybrid", flaky, sleep=waits.append)
        self.assertEqual(out.mood, "intense")
        self.assertEqual(waits, [2, 4])  # exponential

    def test_other_errors_raise_label_error(self):
        def broken(prompt):
            raise FakeApiError(400)
        with self.assertRaises(ai.LabelError):
            ai.label_track(TRACK, "hybrid", broken, sleep=lambda s: None)


class GeminiLabelerTests(unittest.TestCase):
    def test_missing_key_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(ai.LabelError):
                ai.GeminiLabeler()

    def test_calls_the_model_with_json_schema_and_returns_text(self):
        client = mock.Mock()
        client.models.generate_content.return_value = mock.Mock(text=GOOD)
        labeler = ai.GeminiLabeler(client=client, model="m")
        self.assertEqual(labeler("prompt text"), GOOD)
        kwargs = client.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "m")
        self.assertEqual(kwargs["contents"], "prompt text")
        cfg = kwargs["config"]
        self.assertEqual(cfg.temperature, 0)
        self.assertEqual(cfg.response_mime_type, "application/json")


if __name__ == "__main__":
    unittest.main()
