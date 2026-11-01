#!/usr/bin/env python3
"""How much connection demand can the reachable nodes actually serve?

Counting how many reachable nodes are over their limit doesn't work well once the
network is already full without any failure: removing the busiest nodes can make
that number go down. So instead we measure how much of the total outbound
connection demand can't be served:

    unmet = sum over v of max(0, in_v - cap)  /  sum over v of in_v

in_v is the number of outbound connections that would go to reachable node v,
using the same wiring as 06_failure_scenarios.py after nodes reconnect. We use
cap = 114 (released Bitcoin Core v27.0 to v31.0, 125 connections) and 189
(master, 200 connections). In practice a refused node would try other peers, so
this is a measure of how much pressure there is, not of lost connectivity.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
fs = importlib.import_module("06_failure_scenarios")
CAPS = {"released (114)": fs.INBOUND_CAP, "master (189)": fs.INBOUND_CAP_MASTER}


def unmet(edges: np.ndarray, pop, alive: np.ndarray, cap: int) -> tuple[float, float]:
    keep = alive[edges[:, 0]] & alive[edges[:, 1]]
    indeg = np.bincount(edges[keep, 1], minlength=pop.n)[alive & pop.reachable]
    total = indeg.sum()
    clear = indeg[pop.net[alive & pop.reachable] == 0]
    return (float(np.clip(indeg - cap, 0, None).sum() / total),
            float(np.clip(clear - cap, 0, None).sum() / max(clear.sum(), 1)))


def main() -> None:
    ip, ov, primary, n_unreach = fs.load_population()
    rows = []
    for n_u, plab in [(0, "reachable only"), (n_unreach, "with non-listening est.")]:
        for seed in fs.SEEDS:
            rng = np.random.default_rng(seed)
            pop = fs.Population(ip, ov["net"].value_counts().to_dict(), n_u, rng, fs.DUAL_STACK)
            for name, mask in fs.scenarios(ip):
                alive = np.ones(pop.n, bool)
                alive[:len(ip)] = ~mask
                e = fs.wire(pop, alive, rng, "netgroup")
                for clab, cap in CAPS.items():
                    u_all, u_clear = unmet(e, pop, alive, cap)
                    rows.append({"population": plab, "seed": seed, "scenario": name, "capacity": clab,
                                 "unmet_share_all": u_all, "unmet_share_clearnet": u_clear})
            print(f"{plab} seed={seed} done", file=sys.stderr, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(fs.TAB / "capacity_unmet.csv", index=False)
    summ = df.groupby(["population", "capacity", "scenario"], sort=False)[
        ["unmet_share_all", "unmet_share_clearnet"]].mean()
    summ.to_csv(fs.TAB / "capacity_unmet_summary.csv")
    print((summ * 100).round(2).to_string())


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
