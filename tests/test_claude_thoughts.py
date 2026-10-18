import json
import os
import re
import unittest

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis", "claude_thoughts.json")
MOODS = {"calm", "mellow", "intense", "upbeat"}


class ClaudeThoughtsSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATH, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_describes_itself_and_its_limits(self):
        for key in ("about", "labelled_on", "labelled_by", "information_used", "known_contamination"):
            self.assertTrue(self.data.get(key), key)

    def test_every_label_is_well_formed(self):
        labels = self.data["labels"]
        self.assertGreaterEqual(len(labels), 1)
        for track_id, (mood, confidence, reason) in labels.items():
            self.assertRegex(track_id, r"^[A-Za-z0-9]{22}$")
            self.assertIn(mood, MOODS)
            self.assertIn(confidence, {"low", "medium", "high"})
            self.assertTrue(reason.strip(), track_id)
            self.assertLess(len(reason), 200, track_id)

    def test_guesses_are_not_claimed_as_confident(self):
        for track_id, (mood, confidence, reason) in self.data["labels"].items():
            if "Guess" in reason or "Do not know" in reason:
                self.assertEqual(confidence, "low", track_id)

    def test_json_has_no_duplicate_ids(self):
        with open(PATH, encoding="utf-8") as f:
            raw = f.read()
        ids = re.findall(r'^\s+"([A-Za-z0-9]{22})":', raw, flags=re.M)
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
