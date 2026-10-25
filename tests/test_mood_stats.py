import math
import unittest

from mood_stats import agreement, cohen_kappa


class MoodStatsTests(unittest.TestCase):
    def test_hand_computed_kappa(self):
        a = ["x", "x", "y", "y"]
        b = ["x", "y", "y", "y"]
        # observed 3/4; chance = 0.5*0.25 + 0.5*0.75 = 0.5; kappa = (0.75 - 0.5) / 0.5
        self.assertAlmostEqual(agreement(a, b), 0.75)
        self.assertAlmostEqual(cohen_kappa(a, b), 0.5)

    def test_perfect_and_chance(self):
        a = ["x", "y", "x", "y"]
        self.assertAlmostEqual(cohen_kappa(a, a), 1.0)
        self.assertAlmostEqual(cohen_kappa(["x", "x", "y", "y"], ["x", "y", "x", "y"]), 0.0)

    def test_undefined_cases(self):
        self.assertTrue(math.isnan(cohen_kappa(["x", "x"], ["x", "x"])))
        self.assertTrue(math.isnan(cohen_kappa([], [])))

    def test_matches_scikit_learn_when_installed(self):
        try:
            from sklearn.metrics import cohen_kappa_score
        except ImportError:
            self.skipTest("scikit-learn not installed")
        a = ["calm", "mellow", "intense", "upbeat", "calm", "intense", "mellow"]
        b = ["calm", "calm", "intense", "mellow", "calm", "upbeat", "mellow"]
        self.assertAlmostEqual(cohen_kappa(a, b), cohen_kappa_score(a, b))

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            agreement(["x"], ["x", "y"])


if __name__ == "__main__":
    unittest.main()
