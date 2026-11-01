"""Concentration measures for a list of groups (ASNs, providers, countries...).

The functions take a pandas Series with one group label per node. Nodes without
a label are left out, and the caller reports how many there were.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def counts_of(labels_or_counts: pd.Series) -> pd.Series:
    s = labels_or_counts
    if not pd.api.types.is_numeric_dtype(s) or s.index.has_duplicates or s.name == "label":
        s = s.dropna().value_counts()
    return s.sort_values(ascending=False).astype(float)


def hhi(counts: pd.Series) -> float:
    """Herfindahl-Hirschman Index, on the usual 0 to 10,000 scale."""
    p = counts / counts.sum()
    return float((p ** 2).sum() * 10_000)


def gini(counts: pd.Series) -> float:
    """Gini coefficient of group sizes. 0 means all groups are equal, close to 1 means one group has nearly everything."""
    x = np.sort(counts.to_numpy(dtype=float))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return float("nan")
    cum = np.cumsum(x)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def topk_share(counts: pd.Series, k: int) -> float:
    return float(counts.iloc[:k].sum() / counts.sum())


def min_groups_for(counts: pd.Series, frac: float) -> int:
    """How many of the largest groups you need to reach at least frac of all nodes."""
    c = (counts.cumsum() / counts.sum()).to_numpy()
    return int(np.searchsorted(c, frac - 1e-12) + 1)


def summary(labels: pd.Series, name: str = "") -> dict:
    """All concentration numbers for one dimension. labels has one entry per node (NaN if unknown)."""
    n_total = int(len(labels))
    counts = labels.dropna().value_counts().astype(float)
    n = counts.sum()
    h = hhi(counts)
    return {
        "dimension": name,
        "nodes_total": n_total,
        "nodes_attributed": int(n),
        "groups": int(len(counts)),
        "top1_label": counts.index[0] if len(counts) else None,
        "top1_share": topk_share(counts, 1),
        "top5_share": topk_share(counts, 5),
        "top10_share": topk_share(counts, 10),
        "hhi": h,
        "effective_groups": 10_000 / h if h else float("nan"),
        "gini": gini(counts),
        "nakamoto_33": min_groups_for(counts, 1 / 3),
        "nakamoto_50": min_groups_for(counts, 0.5),
    }


def lorenz(counts: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Cumulative share of nodes against cumulative share of groups, biggest groups first."""
    c = counts.sort_values(ascending=False).to_numpy(dtype=float)
    x = np.arange(0, len(c) + 1) / len(c)
    y = np.concatenate([[0], np.cumsum(c) / c.sum()])
    return x, y
