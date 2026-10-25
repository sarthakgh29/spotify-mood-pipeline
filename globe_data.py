"""Data for the song globe: a map of your songs in which songs you played in the same sittings sit close together.

Same idea as the song map in Johan's Lifetime-Wrapped project (js/embed.js), done here in Python so the dashboard page only has to
draw it. Steps:
  1. split the real plays into sessions (30 minutes of silence ends a sitting)
  2. songs x sessions matrix, busy sessions counting for less, rows scaled to length 1
  3. a low-rank "listened together" embedding (truncated SVD)
  4. t-SNE down to two dimensions for the most played songs (the skeleton of the map)
  5. every other song goes to the weighted middle of the skeleton songs it is closest to
Songs are merged by title and artist (wrapped.py), most played first. The result is the same for the same history (seeded).
"""
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.manifold import TSNE

import wrapped as w

SESSION_GAP_MIN = 30
MAP_SIZE = 1000          # the map is scaled into a 0..MAP_SIZE square
NEIGHBOURS = 6           # skeleton songs a non-skeleton song is placed between
MIN_SONGS, MIN_SESSIONS, MIN_CORE = 60, 10, 40


def _normalise_rows(m):
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _sessions(real, index):
    """(session id, song index) pairs, one per song per session, for sessions with at least two different songs."""
    r = real.sort_values("played_at")
    end = r["played_at"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    length = (r["seconds_played"].fillna(0).to_numpy() * 1e9).astype("int64").astype("timedelta64[ns]")
    start = end - length
    new = np.concatenate([[True], (start[1:] - end[:-1]) > np.timedelta64(SESSION_GAP_MIN, "m")])
    pairs = pd.DataFrame({"s": np.cumsum(new) - 1, "i": r["song_key"].map(index).to_numpy()}).drop_duplicates()
    size = pairs.groupby("s")["i"].transform("size")
    pairs = pairs[size >= 2].copy()
    pairs["size"] = size[size >= 2]
    return pairs


def build_song_space(real, core_size=1200, seed=7):
    """Every song in `real` (real plays, as prepared by wrapped.prepare) placed on a 0..1000 square.

    Returns {"songs": [...], "years": [...]}; each song is {i, x, y, plays, first, last, name, artist, id, yr}, where yr is plays per year.
    Returns {"songs": [], "years": [], "reason": "few"} when there is too little history to map.
    """
    top = w._songs(real).reset_index(drop=True)
    n = len(top)
    if n < MIN_SONGS:
        return {"songs": [], "years": [], "reason": "few"}
    index = {k: i for i, k in enumerate(top["song_key"])}
    years = [int(y) for y in sorted(real["year"].unique())]
    yr = (pd.crosstab(real["song_key"].map(index), real["year"]).reindex(index=range(n), columns=years, fill_value=0)).to_numpy()

    pairs = _sessions(real, index)
    keep = pairs["s"].unique()
    if len(keep) < MIN_SESSIONS:
        return {"songs": [], "years": [], "reason": "few"}
    col = pd.Series(np.arange(len(keep)), index=keep)
    weight = 1.0 / np.log(2 + pairs["size"].to_numpy())
    mat = sparse.csr_matrix((weight, (pairs["i"].to_numpy(), col.loc[pairs["s"]].to_numpy())), shape=(n, len(keep)))
    counts = np.asarray((mat > 0).sum(axis=1)).ravel()
    sq = np.sqrt(np.asarray(mat.multiply(mat).sum(axis=1)).ravel())
    sq[sq == 0] = 1.0
    mat = sparse.diags(1.0 / sq) @ mat

    k = min(24, n - 1, len(keep) - 1)
    emb = _normalise_rows(TruncatedSVD(n_components=k, n_iter=7, random_state=seed).fit_transform(mat))

    core = np.flatnonzero(counts > 0)[:core_size]            # most played first, because `top` is sorted that way
    if len(core) < MIN_CORE:
        return {"songs": [], "years": [], "reason": "few"}
    ec = emb[core]
    yc = TSNE(n_components=2, perplexity=min(25.0, (len(core) - 1) / 3), init="pca", learning_rate="auto",
              random_state=seed).fit_transform(ec)

    rand = np.random.default_rng(seed)
    xy = np.zeros((n, 2))
    placed = np.zeros(n, dtype=bool)
    xy[core] = yc
    placed[core] = True
    jitter = (yc[:, 0].max() - yc[:, 0].min()) * 0.004
    others = np.flatnonzero((counts > 0) & ~placed)
    if len(others):
        sims = emb[others] @ ec.T
        nb = min(NEIGHBOURS, len(core))
        best = np.argpartition(-sims, nb - 1, axis=1)[:, :nb]
        dots = np.take_along_axis(sims, best, axis=1)
        wts = 1.0 / (np.sqrt(np.clip(2 - 2 * dots, 0, None)) + 1e-3)
        xy[others] = (yc[best] * wts[..., None]).sum(axis=1) / wts.sum(axis=1, keepdims=True) + rand.normal(size=(len(others), 2)) * jitter
        placed[others] = True

    # songs never played alongside another one carry no listening signal: beside their artist's other songs, else anywhere inside the map
    artists = top["artist_name"].fillna("").to_numpy()
    lo, hi = xy[placed].min(axis=0), xy[placed].max(axis=0)
    centre = {}
    for a in np.unique(artists[placed]):
        centre[a] = xy[placed & (artists == a)].mean(axis=0)
    for i in np.flatnonzero(~placed):
        if artists[i] in centre:
            xy[i] = centre[artists[i]] + rand.normal(size=2) * jitter * 3
        else:
            xy[i] = lo + rand.random(2) * (hi - lo)

    lo = xy.min(axis=0)
    scale = MAP_SIZE / max((xy.max(axis=0) - lo).max(), 1e-9)
    xy = (xy - lo) * scale

    songs = []
    for i, row in enumerate(top.itertuples(index=False)):
        seen = np.flatnonzero(yr[i] > 0)
        songs.append({"i": i, "x": round(float(xy[i, 0]), 2), "y": round(float(xy[i, 1]), 2), "plays": int(row.plays),
                      "first": years[seen[0]] if len(seen) else years[0], "last": years[seen[-1]] if len(seen) else years[-1],
                      "name": row.track_name or "", "artist": row.artist_name or "", "id": row.track_id, "yr": [int(v) for v in yr[i]]})
    return {"songs": songs, "years": years}
