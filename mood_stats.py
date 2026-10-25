"""Agreement statistics for comparing two mood labellings (pure Python, no dependencies)."""
from collections import Counter


def agreement(a, b):
    """Share of positions where the two label lists are equal."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        raise ValueError("label lists must be the same length")
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else float("nan")


def cohen_kappa(a, b):
    """Cohen's kappa: agreement beyond what the two labellings' own label frequencies would give by chance.
    1 = perfect, 0 = no better than chance, negative = worse than chance. NaN if undefined."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        raise ValueError("label lists must be the same length")
    n = len(a)
    if n == 0:
        return float("nan")
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return float("nan")
    return (observed - expected) / (1 - expected)
