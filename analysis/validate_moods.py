"""Compare the genre-based mood with the audio-based mood: percent agreement, confusion matrix, Cohen's kappa.

    python analysis/export_mood_data.py
    python analysis/validate_moods.py

Reports at two levels: distinct tracks, and primary artists (an artist's audio mood is the most common audio
mood across their tracks). Confusion-matrix rows are the genre mood, columns the audio mood.
"""
import os
import sys

import pandas as pd
from sklearn.metrics import cohen_kappa_score, confusion_matrix

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
MOODS = ["calm", "mellow", "intense", "upbeat"]


def interpret(kappa):
    """Landis and Koch (1977) rule-of-thumb wording for kappa."""
    if pd.isna(kappa):
        return "undefined (too few rows, or one method uses a single label)"
    for cut, text in ((0.8, "almost perfect"), (0.6, "substantial"), (0.4, "moderate"), (0.2, "fair"), (0.0, "slight")):
        if kappa > cut:
            return text
    return "no better than chance (or worse)"


def report(name, df):
    print(f"\n=== {name} (n = {len(df)}) ===")
    if df.empty:
        print("No rows with both labels yet.")
        return
    genre, audio = df["genre_mood"], df["audio_mood"]
    agreement = (genre == audio).mean()
    kappa = cohen_kappa_score(genre, audio, labels=MOODS)
    print(f"Percent agreement: {100 * agreement:.1f}%")
    print(f"Cohen's kappa:     {kappa:.3f}  -> {interpret(kappa)}")
    cm = pd.DataFrame(confusion_matrix(genre, audio, labels=MOODS), index=MOODS, columns=MOODS)
    print("Confusion matrix (rows = genre mood, columns = audio mood):")
    print(cm.to_string())
    cm.to_csv(os.path.join(OUT_DIR, f"confusion_{name.split()[0].lower()}.csv"))
    shares = genre.value_counts(normalize=True)
    if len(df) < 30 or shares.iloc[0] > 0.7:
        print("Caution: small sample or one genre mood dominates, so kappa is unstable; don't over-read it.")


def main():
    frames = {}
    for level, table in (("tracks", "mood_comparison_track"), ("artists", "mood_comparison_artist")):
        path = os.path.join(OUT_DIR, f"{table}.csv")
        if not os.path.exists(path):
            print(f"Missing {path}. Run: python analysis/export_mood_data.py")
            return 1
        frames[level] = pd.read_csv(path)
    report("Track level", frames["tracks"])
    report("Artist level", frames["artists"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
