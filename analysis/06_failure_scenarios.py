#!/usr/bin/env python3
"""What happens if large providers, ASes or countries go offline?

This has two parts and we keep them apart on purpose.

Part A just counts. For each scenario we look at how many of the nodes we can
actually see would disappear, using three different totals, and how much
diversity is left.

Part B is a model. Nobody can see the real Bitcoin topology, so we build random
networks that follow Bitcoin Core's rules for outbound connections:
  - each node opens 8 full-relay and 2 block-relay-only outbound connections
  - its IPv4/IPv6 peers must come from different netgroups (/16 or /32),
    or from different ASNs when -asmap is on
  - only listening nodes accept connections. Inbound slots are the connection
    limit minus the 11 automatic outbound slots: 114 in released versions
    (limit 125) and 189 on master (limit 200)
Apart from that, peers are picked at random. Real nodes use addrman's bucket
logic, which this only approximates, so everything from Part B is labelled as
model output.

The model population is: the reachable SHA256d-chain nodes from the main dataset
(functional, chain_view tip or below_tip), the Tor/I2P nodes from D2 on the same
chain, and optionally the non-listening nodes estimated by Luke Dashjr.

Run with --figures-only to redraw the figures from saved results without
running the model again.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, shortest_path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from lib import metrics as M  # noqa: E402
from lib.plotstyle import INK2, MUTED, SERIES, plt, source_note  # noqa: E402

PROC, TAB, FIG, RAW = ROOT / "data" / "processed", ROOT / "tables", ROOT / "figures", ROOT / "data" / "raw"
# Set BII_PROCESSED=data/public/processed to run on the pseudonymised public data instead.
PROC = Path(os.environ.get("BII_PROCESSED", PROC))
N_FULL, N_BLOCK = 8, 2
# Inbound slots are -maxconnections minus the automatic outbound slots (8 + 2 + 1 feeler).
# See m_max_inbound in net.h.
# Releases v27.0 to v31.0 use 125 connections by default (data/raw/bitcoin-core/v31.0/net.h).
# Only master uses 200, which we keep as a second case.
INBOUND_CAP = 125 - N_FULL - N_BLOCK - 1          # 114, released versions
INBOUND_CAP_MASTER = 200 - N_FULL - N_BLOCK - 1   # 189, master branch
DUAL_STACK = 0.25  # assumed share of nodes that also use an overlay network (sensitivity: 0)
SEEDS = [1, 2, 3]
HOP_SOURCES = 40


def load_population() -> tuple[pd.DataFrame, pd.DataFrame, str, int]:
    primary = "D2"  # D1 IPv4 coverage is degraded by the vantage point (see 02b_reprobe_diagnostic.py)
    f = "d1_crawl_nodes.csv" if primary == "D1" else "d2_bitnodes_nodes.csv"
    ip = pd.read_csv(PROC / f, low_memory=False)
    ip = ip[ip["functional"] & ip["chain_view"].isin(["tip", "below_tip"])].copy()
    ov = pd.read_csv(PROC / "d2_bitnodes_overlay.csv")
    ov = ov[ov["functional"] & ov["chain_view"].isin(["tip", "below_tip"])].copy()
    luke = json.load(open(RAW / "luke_uainfo.json"))
    n_unreach = int(sum(v.get("est_unreachable", 0) for v in luke.values()))
    return ip, ov, primary, n_unreach


def scenarios(ip: pd.DataFrame) -> list[tuple[str, np.ndarray]]:
    prov = ip["provider"].value_counts()
    asn = ip["asn"].value_counts()
    cc = ip["geo_cc"].value_counts()
    out = [("Baseline (no failure)", np.zeros(len(ip), bool)),
           (f"Largest ASN (AS{int(asn.index[0])})", (ip["asn"] == asn.index[0]).to_numpy()),
           (f"Largest provider ({prov.index[0]})", (ip["provider"] == prov.index[0]).to_numpy()),
           (f"Largest country ({cc.index[0]})", (ip["geo_cc"] == cc.index[0]).to_numpy()),
           ("Top-5 providers", ip["provider"].isin(prov.index[:5]).to_numpy()),
           ("Top-10 providers", ip["provider"].isin(prov.index[:10]).to_numpy()),
           ("All hosted (H1+H2)", ip["infra_class"].isin(["H1", "H2"]).to_numpy())]
    return out


# A. static accounting
def static_table(ip: pd.DataFrame, ov: pd.DataFrame, n_unreach: int) -> pd.DataFrame:
    rows = []
    n_ip, n_ov = len(ip), len(ov)
    for name, mask in scenarios(ip):
        lost = int(mask.sum())
        rest = ip[~mask]
        frac_ip = lost / n_ip
        rows.append({
            "scenario": name, "nodes_lost": lost,
            "share_of_ip_reachable": frac_ip,
            "share_of_all_reachable": lost / (n_ip + n_ov),
            "share_of_all_incl_unreachable_A": lost / (n_ip + n_ov + n_unreach),
            "share_of_all_incl_unreachable_B": (lost + frac_ip * n_unreach) / (n_ip + n_ov + n_unreach),
            "remaining_ip_nodes": len(rest), "remaining_asns": rest["asn"].nunique(),
            "remaining_countries": rest["geo_cc"].nunique(),
            "remaining_provider_hhi": M.hhi(rest["provider"].value_counts()) if len(rest) else np.nan,
        })
    return pd.DataFrame(rows)


# B. topology model
class Population:
    """Per-node arrays for the model (network, groups, provider, which networks it can use)."""

    def __init__(self, ip: pd.DataFrame, n_ov: dict[str, int], n_unreach: int, rng: np.random.Generator,
                 dual: float):
        n_ip = len(ip)
        n_tor, n_i2p = n_ov.get("onion", 0), n_ov.get("i2p", 0)
        self.n_reach = n_ip + n_tor + n_i2p
        self.n = self.n_reach + n_unreach
        # network: 0 = clearnet, 1 = onion, 2 = i2p
        self.net = np.concatenate([np.zeros(n_ip, int), np.ones(n_tor, int), np.full(n_i2p, 2), np.zeros(n_unreach, int)])
        self.reachable = np.arange(self.n) < self.n_reach
        # groups used for outbound diversity. Tor/I2P get the network id plus 4 random bits, like GetGroup does.
        ng = pd.factorize(ip["netgroup"])[0]
        asg = pd.factorize(ip["asn"].astype(str))[0]
        ovg = 10_000_000 + self.net[n_ip:self.n_reach] * 16 + rng.integers(0, 16, n_tor + n_i2p)
        self.group_ng = np.concatenate([ng, ovg, np.full(n_unreach, -1)])
        self.group_as = np.concatenate([asg, ovg, np.full(n_unreach, -1)])
        self.provider = np.concatenate([ip["provider"].astype(str).to_numpy(), np.full(n_tor + n_i2p, "(overlay)"),
                                        np.full(n_unreach, "(unreachable)")])
        # which networks each node can use for outbound connections
        self.uses_clear = self.net == 0
        self.uses_overlay = self.net > 0
        dual_mask = rng.random(self.n) < dual
        self.uses_clear |= dual_mask & (self.net > 0)
        self.uses_overlay |= dual_mask & (self.net == 0)


def wire(pop: Population, alive: np.ndarray, rng: np.random.Generator, mode: str) -> np.ndarray:
    """Picks outbound peers for every live node. Returns rows of [from, to, is_full_relay]."""
    group = pop.group_ng if mode == "netgroup" else pop.group_as
    cand_clear = np.flatnonzero(alive & pop.reachable & (pop.net == 0))
    cand_ov = np.flatnonzero(alive & pop.reachable & (pop.net > 0))
    edges = []
    want = N_FULL + N_BLOCK
    for u in np.flatnonzero(alive):
        pools = []
        if pop.uses_clear[u] and len(cand_clear):
            pools.append(cand_clear)
        if pop.uses_overlay[u] and len(cand_ov):
            pools.append(cand_ov)
        if not pools:
            continue
        seen_groups, chosen = set(), []
        # Core tries to keep at least one outbound peer in each network it can reach (MaybePickPreferredNetwork)
        for k in range(want * 6):
            pool = pools[k % len(pools)] if len(chosen) < len(pools) else pools[rng.integers(len(pools))]
            v = pool[rng.integers(len(pool))]
            g = group[v]
            if v == u or g in seen_groups:
                continue
            seen_groups.add(g)
            chosen.append(v)
            if len(chosen) == want:
                break
        for i, v in enumerate(chosen):
            edges.append((u, v, 1 if i < N_FULL else 0))
    return np.asarray(edges, dtype=np.int64).reshape(-1, 3)


def graph_metrics(pop: Population, edges: np.ndarray, alive: np.ndarray, rng: np.random.Generator) -> dict:
    keep = alive[edges[:, 0]] & alive[edges[:, 1]]
    e = edges[keep]
    n_alive = int(alive.sum())
    outdeg = np.bincount(e[:, 0], minlength=pop.n)
    zero_out = float(((outdeg == 0) & alive).sum() / n_alive)
    full = e[e[:, 2] == 1]
    full_deg = np.bincount(full[:, 0], minlength=pop.n)
    zero_full = float(((full_deg == 0) & alive).sum() / n_alive)
    A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(pop.n, pop.n)).tocsr()
    ncomp, lab = connected_components(A, directed=False)
    sizes = np.bincount(lab[alive])
    lcc = float(sizes.max() / n_alive)
    # average number of hops, once over full-relay links only (roughly how transactions
    # travel) and once over all links (roughly how blocks travel), from random starting nodes
    big = np.flatnonzero(alive & (lab == np.argmax(np.bincount(lab, weights=alive))))
    src = rng.choice(big, size=min(HOP_SOURCES, len(big)), replace=False)
    Af = coo_matrix((np.ones(len(full)), (full[:, 0], full[:, 1])), shape=(pop.n, pop.n)).tocsr()
    d_all = shortest_path(A, directed=False, unweighted=True, indices=src)
    d_full = shortest_path(Af, directed=False, unweighted=True, indices=src)
    fin_a = d_all[:, alive][np.isfinite(d_all[:, alive])]
    fin_f = d_full[:, alive][np.isfinite(d_full[:, alive])]
    indeg = np.bincount(e[:, 1], minlength=pop.n)[alive & pop.reachable]
    return {"zero_outbound": zero_out, "zero_full_relay": zero_full, "lcc": lcc,
            "mean_hops_all": float(fin_a.mean()), "p99_hops_all": float(np.percentile(fin_a, 99)),
            "mean_hops_full": float(fin_f.mean()),
            "full_relay_reach": float(len(fin_f) / (len(src) * n_alive)),
            "mean_inbound": float(indeg.mean()), "max_inbound": int(indeg.max()),
            "share_reachable_over_cap": float((indeg > INBOUND_CAP).mean()),
            "share_reachable_over_cap_master": float((indeg > INBOUND_CAP_MASTER).mean()),
            "p99_inbound": float(np.percentile(indeg, 99))}


def eclipse_exposure(pop: Population, edges: np.ndarray, top_providers: list[str]) -> dict:
    """How often a node's outbound peers sit mostly or entirely in one provider."""
    # Only clearnet peers have a known provider, so nodes with fewer than four clearnet
    # peers (mostly Tor/I2P-only nodes) are left out here.
    prov = pop.provider[edges[:, 1]]
    df = pd.DataFrame({"u": edges[:, 0], "p": prov, "full": edges[:, 2]})
    df = df[df.p != "(overlay)"]
    n_clear = df.groupby("u").size()
    df = df[df.u.isin(n_clear[n_clear >= 4].index)]
    cnt = df.groupby(["u", "p"]).size()
    tot = df.groupby("u").size()
    top_share = (cnt.groupby(level=0).max() / tot)
    out = {"nodes_evaluated": int(len(tot)),
           "all_clearnet_outbound_one_provider": float((top_share == 1.0).mean()),
           "majority_clearnet_outbound_one_provider": float((top_share > 0.5).mean()),
           "mean_max_provider_share": float(top_share.mean())}
    top = top_providers[0]
    f = df[df.full == 1]
    share_top = f.assign(t=f.p == top).groupby("u")["t"].mean()
    out["top_provider"] = top
    out["ge50pct_full_relay_in_top_provider"] = float((share_top >= 0.5).mean())
    return out


def run_model(ip: pd.DataFrame, ov: pd.DataFrame, n_unreach_est: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_ov = ov["net"].value_counts().to_dict()
    rows, ecl = [], []
    top_prov = ip["provider"].value_counts().index.tolist()
    for n_unreach, ulab in [(0, "reachable only"), (n_unreach_est, "with non-listening est.")]:
        for dual, dlab in [(DUAL_STACK, f"dual-stack {DUAL_STACK:.0%}"), (0.0, "dual-stack 0%")]:
            if dual == 0.0 and n_unreach == 0:
                continue  # keep the grid small; the 0% case is a sensitivity for the full population
            for seed in SEEDS:
                rng = np.random.default_rng(seed)
                pop = Population(ip, n_ov, n_unreach, rng, dual)
                for mode in ["netgroup", "asmap"]:
                    if mode == "asmap" and (dual == 0.0 or seed != SEEDS[0]):
                        continue
                    all_alive = np.ones(pop.n, bool)
                    base_edges = wire(pop, all_alive, rng, mode)
                    if dual == DUAL_STACK:
                        e = eclipse_exposure(pop, base_edges, top_prov)
                        ecl.append({"population": ulab, "mode": mode, "seed": seed, **e})
                    for name, mask in scenarios(ip):
                        alive = all_alive.copy()
                        alive[:len(ip)] = ~mask
                        # non-listening nodes are assumed to stay online (assumption A)
                        m_now = graph_metrics(pop, base_edges, alive, rng)
                        rewired = wire(pop, alive, rng, mode)
                        m_after = graph_metrics(pop, rewired, alive, rng)
                        rows.append({"population": ulab, "dual_stack": dlab, "mode": mode, "seed": seed,
                                     "scenario": name, "nodes_in_model": int(alive.sum()),
                                     **{f"now_{k}": v for k, v in m_now.items()},
                                     **{f"after_{k}": v for k, v in m_after.items()}})
                        print(f"{ulab:24s} {dlab:15s} {mode:8s} seed={seed} {name:32s} "
                              f"LCC now={m_now['lcc']:.4f} zero_out={m_now['zero_outbound']:.4f} "
                              f"hops={m_now['mean_hops_all']:.2f}->{m_after['mean_hops_all']:.2f} "
                              f"inbound={m_after['mean_inbound']:.1f}", file=sys.stderr, flush=True)
    return pd.DataFrame(rows), pd.DataFrame(ecl)


def fig_static(st: pd.DataFrame, primary: str, note: str) -> None:
    s = st[st.scenario != "Baseline (no failure)"].iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    y = np.arange(len(s))
    h = 0.27
    cols = [("share_of_ip_reachable", "of IPv4/IPv6-reachable nodes"),
            ("share_of_all_reachable", "of all reachable incl. Tor/I2P"),
            ("share_of_all_incl_unreachable_A", "of reachable + est. non-listening (unaffected)")]
    for i, (c, lab) in enumerate(cols):
        ax.barh(y + (1 - i) * h, s[c] * 100, height=h * 0.9, color=SERIES[i], label=lab)
        for yy, v in zip(y + (1 - i) * h, s[c] * 100):
            ax.text(v + 0.6, yy, f"{v:.1f}", va="center", fontsize=6, color=INK2)
    ax.set_yticks(y)
    ax.set_yticklabels(s["scenario"])
    ax.set_xlabel("Observable nodes removed (%)")
    ax.set_title(f"Hypothetical failures: share of nodes removed ({primary})")
    ax.grid(axis="y", visible=False)
    ax.legend(fontsize=6.5, loc="upper center", bbox_to_anchor=(0.4, -0.18), ncol=2)
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"failure_scenarios.{ext}")
    plt.close(fig)


def fig_model(mt: pd.DataFrame, note: str) -> None:
    d = mt[(mt["mode"] == "netgroup") & (mt["dual_stack"].str.contains("25"))]
    g = d.groupby(["population", "scenario"], sort=False).agg(
        lcc=("now_lcc", "mean"), zero=("now_zero_outbound", "mean"),
        hops_now=("now_mean_hops_all", "mean"), hops_after=("after_mean_hops_all", "mean")).reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.0), sharey=True)
    for ax, (metric, lab) in zip(axes, [("zero", "Nodes left with 0 outbound peers (%)"),
                                        ("hops_now", "Mean hop distance before re-connection")]):
        for i, pop in enumerate(g["population"].unique()):
            s = g[g.population == pop]
            y = np.arange(len(s)) + (i - 0.5) * 0.35
            v = s[metric] * (100 if metric == "zero" else 1)
            ax.barh(y, v, height=0.32, color=SERIES[i], label=pop)
        ax.set_xlabel(lab, fontsize=7.5)
        ax.grid(axis="y", visible=False)
        if metric == "zero":
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.3f}"))
            ax.tick_params(axis="x", labelsize=6.5, rotation=30)
    axes[0].set_yticks(np.arange(len(s)))
    axes[0].set_yticklabels(s["scenario"], fontsize=7)
    axes[0].legend(fontsize=6.5, loc="upper center", bbox_to_anchor=(1.0, -0.3), ncol=2)
    fig.suptitle("Synthetic topology model (not a measurement): immediate effect of failures", x=0.0, ha="left",
                 fontsize=10, fontweight="bold")
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"failure_model.{ext}")
    plt.close(fig)


def main() -> None:
    ip, ov, primary, n_unreach = load_population()
    st = static_table(ip, ov, n_unreach)
    st.to_csv(TAB / "failure_static.csv", index=False)
    print(st.to_string(), file=sys.stderr)
    t = st[["scenario", "nodes_lost", "share_of_ip_reachable", "share_of_all_reachable",
            "share_of_all_incl_unreachable_A", "share_of_all_incl_unreachable_B", "remaining_asns",
            "remaining_countries"]].copy()
    for c in ["share_of_ip_reachable", "share_of_all_reachable", "share_of_all_incl_unreachable_A",
              "share_of_all_incl_unreachable_B"]:
        t[c] = (t[c] * 100).round(1)
    t.columns = ["Scenario", "Lost", "% IP", "% reach.", "% all (A)", "% all (B)", "ASNs left", "Countries left"]
    from importlib import import_module
    to_tex = import_module("05_concentration").to_tex
    to_tex(t, TAB / "failure_static.tex",
           f"Static accounting of hypothetical failures ({primary}, SHA256d-chain functional IPv4/IPv6 nodes). "
           "\\% all (A): non-listening nodes (Luke Dashjr estimate) assumed unaffected; (B): affected in the same "
           "proportion as reachable IP nodes.", "tab:failstatic", colfmt="lrrrrrrr", float_fmt="{:.1f}")
    meta = {"primary": primary, "ip_nodes": len(ip), "overlay_nodes": ov["net"].value_counts().to_dict(),
            "n_unreach_luke": n_unreach, "inbound_cap": INBOUND_CAP,
            "inbound_cap_master": INBOUND_CAP_MASTER, "dual_stack": DUAL_STACK, "seeds": SEEDS}
    (TAB / "failure_meta.json").write_text(json.dumps(meta, indent=2))
    fig_static(st, primary, f"Data: {primary} functional SHA256d-chain IPv4/IPv6 nodes (n = {len(ip):,}); D2 Tor/I2P "
                            f"(n = {len(ov):,}); non-listening estimate {n_unreach:,} (Luke Dashjr, 2026-10-04).")
    if "--figures-only" in sys.argv:  # re-draw outputs from saved model results, no re-simulation
        fig_model(pd.read_csv(TAB / "failure_model.csv"),
                  f"Model: 8 full-relay + 2 block-relay outbound per node, distinct /16 (/32) netgroups, uniform peer "
                  f"choice; 25% of nodes dual-stack; {len(SEEDS)} seeds (means). Non-listening nodes assumed unaffected.")
        return
    mt, ecl = run_model(ip, ov, n_unreach)
    mt.to_csv(TAB / "failure_model.csv", index=False)
    ecl.to_csv(TAB / "eclipse_exposure.csv", index=False)
    fig_model(mt, f"Model: 8 full-relay + 2 block-relay outbound per node, distinct /16 (/32) netgroups, uniform peer "
                  f"choice; 25% of nodes dual-stack; {len(SEEDS)} seeds (means). Population as in Fig. "
                  "failure_scenarios. Non-listening nodes assumed unaffected.")
    summ = mt.groupby(["population", "dual_stack", "mode", "scenario"], sort=False).mean(numeric_only=True)
    summ.to_csv(TAB / "failure_model_summary.csv")
    print(summ[["now_lcc", "now_zero_outbound", "now_mean_hops_all", "after_mean_hops_all",
                "after_mean_inbound", "after_max_inbound"]].round(4).to_string())
    print(ecl.groupby(["population", "mode"]).mean(numeric_only=True).to_string())


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
