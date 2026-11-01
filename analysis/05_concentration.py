#!/usr/bin/env python3
"""Concentration numbers, tables and most of the figures.

Reads the tables made by 04_build_datasets.py and writes tables/*.csv, tables/*.tex
and figures/*.pdf/png.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from lib import metrics as M  # noqa: E402
from lib.plotstyle import INK2, MUTED, SERIES, plt, source_note  # noqa: E402

PROC, TAB, FIG = ROOT / "data" / "processed", ROOT / "tables", ROOT / "figures"
# Set BII_PROCESSED=data/public/processed to run on the pseudonymised public data instead.
PROC = Path(os.environ.get("BII_PROCESSED", PROC))
CLASS_LABEL = {"H1": "H1 cloud (published ranges)", "H2": "H2 hosting (ASN-level)",
               "R": "R residential/access", "U": "U unclassified"}


def load() -> dict[str, pd.DataFrame]:
    ds = {}
    if (PROC / "d1_crawl_nodes.csv").exists():
        ds["D1"] = pd.read_csv(PROC / "d1_crawl_nodes.csv", low_memory=False)
    if (PROC / "d1b_crawl_nodes.csv").exists():
        ds["D1b"] = pd.read_csv(PROC / "d1b_crawl_nodes.csv", low_memory=False)
    ds["D2"] = pd.read_csv(PROC / "d2_bitnodes_nodes.csv", low_memory=False)
    kit = sorted(glob.glob(str(PROC / "d3_kit_20261003_*.csv")))[-1]
    ds["D3"] = pd.read_csv(kit, low_memory=False)
    # extra versions of each dataset with only NODE_WITNESS nodes (added after pre-registration)
    for k in list(ds):
        ds[k + "f"] = ds[k][ds[k]["functional"]].copy()
    for k, df in ds.items():
        if "asn" in df:
            df["asn_label"] = df["asn"].map(lambda a: f"AS{int(a)}" if pd.notna(a) else np.nan)
    return ds


DIMS_IP = [("Country (geolocation, DB-IP)", "geo_cc"), ("Country (RIR registration)", "rir_cc"),
           ("ASN", "asn_label"), ("Organisation (CAIDA AS2Org)", "org"),
           ("Provider (sibling-merged)", "provider"), ("IPv4 /24 | IPv6 /48 subnet", "subnet"),
           ("Client software", "client")]
DIMS_KIT = [("Country (AS registration, KIT whois)", "kit_asn_cc"), ("ASN", "asn_label"),
            ("Organisation (CAIDA AS2Org)", "org"), ("Provider (sibling-merged)", "provider"),
            ("Client software", "client")]


def to_tex(df: pd.DataFrame, path: Path, caption: str, label: str, colfmt: str | None = None,
           float_fmt: str = "{:.3f}") -> None:
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda x: "" if pd.isna(x) else float_fmt.format(x))
    d = d.astype(str).apply(lambda col: col.str.replace("&", r"\&").str.replace("%", r"\%")
                            .str.replace("_", r"\_").str.replace("#", r"\#"))
    cols = [str(c).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&") for c in d.columns]
    colfmt = colfmt or "l" + "r" * (len(cols) - 1)
    lines = [r"\begin{table}[t]", r"\centering\small", f"\\caption{{{caption}}}", f"\\label{{{label}}}",
             r"\resizebox{\linewidth}{!}{%" if len(cols) > 7 else "",
             f"\\begin{{tabular}}{{{colfmt}}}", r"\toprule", " & ".join(cols) + r" \\", r"\midrule"]
    lines += [" & ".join(r) + r" \\" for r in d.values.tolist()]
    lines += [r"\bottomrule", r"\end{tabular}" + ("}" if len(cols) > 7 else ""), r"\end{table}"]
    path.write_text("\n".join(lines) + "\n")


def concentration_table(ds: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for key, df in ds.items():
        dims = DIMS_KIT if key.startswith("D3") else DIMS_IP
        for name, col in dims:
            s = M.summary(df[col], name)
            if col == "subnet":
                s["top1_label"] = "(withheld)"  # a /24 or /48 can identify an operator
            s["dataset"] = key
            rows.append(s)
    out = pd.DataFrame(rows)
    cols = ["dataset", "dimension", "nodes_total", "nodes_attributed", "groups", "top1_label",
            "top1_share", "top5_share", "top10_share", "hhi", "effective_groups", "gini",
            "nakamoto_33", "nakamoto_50"]
    return out[cols]


def top_table(df: pd.DataFrame, col: str, n: int = 10, extra: dict | None = None) -> pd.DataFrame:
    c = df[col].dropna().value_counts()
    t = pd.DataFrame({"group": c.index[:n], "nodes": c.values[:n]})
    t["share_attributable"] = t["nodes"] / c.sum()
    t["cumulative"] = t["share_attributable"].cumsum()
    if extra:
        for k, denom in extra.items():
            t[k] = t["nodes"] / denom
    return t


def class_table(ds: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for key, df in ds.items():
        vc = df["infra_class"].value_counts()
        n = len(df)
        r = {"dataset": key, "nodes": n}
        for c in ["H1", "H2", "R", "U"]:
            r[c] = vc.get(c, 0) / n
        r["hosted_lower(H1)"] = r["H1"]
        r["hosted_central(H1+H2)"] = r["H1"] + r["H2"]
        r["hosted_upper(H1+H2+U)"] = r["H1"] + r["H2"] + r["U"]
        r["residential_central(R)"] = r["R"]
        rows.append(r)
    return pd.DataFrame(rows)


def class_reason_table(df: pd.DataFrame) -> pd.DataFrame:
    t = df.groupby(["infra_class", "class_reason"]).size().rename("nodes").reset_index()
    t["share"] = t["nodes"] / len(df)
    return t.sort_values(["infra_class", "nodes"], ascending=[True, False])


def geo_agreement(df: pd.DataFrame) -> dict:
    both = df.dropna(subset=["geo_cc", "rir_cc"])
    agree = (both["geo_cc"] == both["rir_cc"]).mean()
    by_class = both.assign(a=both["geo_cc"] == both["rir_cc"]).groupby("infra_class")["a"].mean().to_dict()
    return {"n": len(both), "agreement": float(agree), **{f"agree_{k}": float(v) for k, v in by_class.items()}}


def cross_dataset_overlap(ds: dict[str, pd.DataFrame], key: str = "D1") -> dict:
    if key not in ds:
        return {}
    a, b = set(ds[key]["ip"]), set(ds["D2"]["ip"])
    return {"D1": len(a), "D2": len(b), "both": len(a & b), "only_D1": len(a - b), "only_D2": len(b - a),
            "jaccard": len(a & b) / len(a | b)}


# figures
def fig_top_bars(df: pd.DataFrame, col: str, title: str, fname: str, note: str, n: int = 15,
                 total_reachable: int | None = None) -> None:
    c = df[col].dropna().value_counts()
    share = (c / c.sum() * 100).iloc[:n][::-1]
    fig, ax = plt.subplots(figsize=(6.2, 0.26 * n + 0.9))
    ax.barh(share.index.astype(str), share.values, color=SERIES[0], height=0.7)
    for y, v in enumerate(share.values):
        ax.text(v + share.max() * 0.01, y, f"{v:.1f}%", va="center", fontsize=7, color=INK2)
    ax.set_xlabel("Share of attributable IPv4/IPv6 nodes (%)")
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, share.max() * 1.15)
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{fname}.{ext}")
    plt.close(fig)


def fig_cumulative(df: pd.DataFrame, note: str, fname: str = "cumulative_concentration") -> None:
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    for (label, col), color in zip([("Provider (merged org)", "provider"), ("ASN", "asn_label"),
                                    ("Country (geolocation)", "geo_cc")], SERIES):
        c = df[col].dropna().value_counts()
        y = np.concatenate([[0], np.cumsum(c.values) / c.sum() * 100])
        x = np.arange(len(y))
        ax.plot(x, y, color=color, label=f"{label} ({len(c)} groups)")
    ax.axhline(50, color=MUTED, lw=0.8, ls="--")
    ax.text(2500, 51.5, "50 %", fontsize=7, color=MUTED, ha="right")
    ax.set_xscale("symlog", linthresh=10)
    ax.set_xlim(0, 3000)
    ax.set_ylim(0, 101)
    ax.set_xlabel("Number of largest groups (symlog scale)")
    ax.set_ylabel("Cumulative share of nodes (%)")
    ax.set_title("Cumulative concentration of observable IPv4/IPv6 nodes")
    ax.legend(loc="lower right", fontsize=7.5)
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{fname}.{ext}")
    plt.close(fig)


def fig_metric_compare(ct: pd.DataFrame, metric: str, ylabel: str, fname: str, title: str, note: str,
                       ref: float | None = None, ref_label: str = "") -> None:
    dims = ["Country (geolocation, DB-IP)", "ASN", "Provider (sibling-merged)"]
    kitmap = {"Country (geolocation, DB-IP)": "Country (AS registration, KIT whois)"}
    datasets = [d for d in ["D1bf", "D2f", "D3f"] if d in set(ct["dataset"])]
    labels = {"D1bf": "D1b own crawl", "D2f": "D2 Bitnodes", "D3f": "D3 KIT DSN"}
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    w = 0.8 / len(datasets)
    for i, d in enumerate(datasets):
        vals = []
        for dim in dims:
            dd = kitmap.get(dim, dim) if d.startswith("D3") else dim
            r = ct[(ct.dataset == d) & (ct.dimension == dd)]
            vals.append(float(r[metric].iloc[0]) if len(r) else np.nan)
        xs = np.arange(len(dims)) + (i - (len(datasets) - 1) / 2) * w
        ax.bar(xs, vals, width=w * 0.92, color=SERIES[i], label=labels[d])
        for x, v in zip(xs, vals):
            if not np.isnan(v):
                ax.text(x, v, f"{v:.0f}" if metric == "hhi" else f"{v:.2f}", ha="center", va="bottom",
                        fontsize=6.5, color=INK2)
    if ref is not None:
        ax.axhline(ref, color=MUTED, lw=0.8, ls="--")
        ax.text(len(dims) - 0.5, ref, ref_label, fontsize=6.5, color=MUTED, ha="right", va="bottom")
    ax.set_xticks(range(len(dims)))
    ax.set_xticklabels(["Country*", "ASN", "Provider"])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{fname}.{ext}")
    plt.close(fig)


def fig_classes(ctab: pd.DataFrame, note: str) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 0.5 * ctab["dataset"].str.endswith("f").sum() + 1.0))
    labels = {"D1f": "D1 own crawl (home)", "D1bf": "D1b own crawl\n(AWS v4 + home v6)", "D2f": "D2 Bitnodes",
              "D3f": "D3 KIT DSN\n(ASN-level only)"}
    colors = {"H1": SERIES[0], "H2": "#86b6ef", "U": "#d6d5d0", "R": SERIES[1]}
    order = ["H1", "H2", "U", "R"]
    rows = [r for r in ctab.itertuples() if r.dataset in labels]
    for y, r in enumerate(rows[::-1]):
        left = 0
        for c in order:
            v = getattr(r, c) * 100
            ax.barh(y, v, left=left, color=colors[c], height=0.6, edgecolor="white", linewidth=1.5,
                    label=CLASS_LABEL[c] if y == 0 else None)
            if v > 4:
                ax.text(left + v / 2, y, f"{v:.0f}%", ha="center", va="center", fontsize=7,
                        color="white" if c in ("H1", "R") else "#0b0b0b")
            left += v
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([labels[r.dataset] for r in rows[::-1]])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of attributable IPv4/IPv6 nodes (%)")
    ax.set_title("Infrastructure class of observable IPv4/IPv6 nodes")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=2, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.35))
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"infra_classes.{ext}")
    plt.close(fig)


def fig_networks(ns: pd.DataFrame, note: str) -> None:
    """Bar of reachable nodes per network type in D2 (Tor/I2P/CJDNS counts verified by Bitnodes)."""
    r = ns[ns.dataset.str.startswith("D2")].iloc[0]
    parts = [("IPv4", r.ipv4), ("IPv6", r.ipv6), ("Tor (onion)", r.onion), ("I2P", r.i2p), ("CJDNS", r.cjdns)]
    tot = sum(p[1] for p in parts)
    fig, ax = plt.subplots(figsize=(6.2, 1.5))
    left = 0
    cols = [SERIES[0], "#86b6ef", SERIES[1], "#f4a582", SERIES[2]]
    for (lab, v), c in zip(parts, cols):
        ax.barh(0, v / tot * 100, left=left, color=c, edgecolor="white", linewidth=1.5, label=f"{lab}: {int(v):,}")
        if v / tot > 0.05:
            ax.text(left + v / tot * 50, 0, f"{v / tot * 100:.0f}%", ha="center", va="center", fontsize=7,
                    color="white")
        left += v / tot * 100
    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.set_xlabel("Share of reachable nodes in D2 (%)")
    ax.set_title(f"Reachable nodes by network type (D2, n = {int(tot):,})")
    ax.grid(False)
    ax.legend(ncol=5, fontsize=6.5, loc="upper center", bbox_to_anchor=(0.5, -0.6))
    source_note(fig, note)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"networks.{ext}")
    plt.close(fig)


def main() -> None:
    TAB.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
    ds = load()
    primary = "D2"  # D1 IPv4 coverage is degraded by the vantage point (see 02b_reprobe_diagnostic.py)
    ns = pd.read_csv(PROC / "networks_summary.csv")
    d2_all = int(ns[ns.dataset.str.startswith("D2")][["ipv4", "ipv6", "onion", "i2p", "cjdns"]].sum(axis=1).iloc[0])

    ct = concentration_table(ds)
    ct.to_csv(TAB / "concentration_summary.csv", index=False)
    sub = ct[ct.dimension.isin(["Country (geolocation, DB-IP)", "Country (AS registration, KIT whois)",
                                "ASN", "Provider (sibling-merged)", "Organisation (CAIDA AS2Org)"])]
    tex = sub[["dataset", "dimension", "nodes_attributed", "groups", "top1_share", "top5_share",
               "top10_share", "hhi", "effective_groups", "gini", "nakamoto_50"]].copy()
    tex.columns = ["Data", "Dimension", "n", "Groups", "Top-1", "Top-5", "Top-10", "HHI", "N_eff", "Gini", "N50"]
    for col in ["Top-1", "Top-5", "Top-10"]:
        tex[col] = (tex[col] * 100).round(1)
    tex["Gini"] = tex["Gini"].round(2)
    tex["HHI"] = tex["HHI"].round(0).astype(int)
    tex["N_eff"] = tex["N_eff"].round(1)
    to_tex(tex, TAB / "concentration_summary.tex",
           "Concentration of observable IPv4/IPv6 nodes (suffix f: NODE\\_WITNESS nodes only). Top-k shares in \\% of attributable nodes; "
           "N\\_eff = 10{,}000/HHI; N50 = smallest number of groups jointly holding at least 50\\% of attributable nodes.",
           "tab:concentration", colfmt="llrrrrrrrrr", float_fmt="{:.1f}")

    # top-10 tables
    for key, df in ds.items():
        cols = [("provider", "provider"), ("asn_label", "asn"), ("org", "org")]
        cols += [("kit_asn_cc", "country")] if key.startswith("D3") else [("geo_cc", "country"), ("rir_cc", "rircountry")]
        for col, tag in cols:
            extra = {"share_all_reachable_incl_overlay": d2_all} if key == "D2" else None
            t = top_table(df, col, 10, extra)
            if col == "asn_label":
                names = df.drop_duplicates("asn_label").set_index("asn_label")
                namecol = "as_name" if "as_name" in names else "kit_as_name"
                t.insert(1, "name", t["group"].map(names[namecol]))
            t.to_csv(TAB / f"top10_{tag}_{key}.csv", index=False)

    p = ds[primary + "f"]  # figures and top-10 tables: functional (NODE_WITNESS) nodes
    tp = top_table(p, "provider", 10)
    asn_t = top_table(p, "asn_label", 10)
    names = p.drop_duplicates("asn_label").set_index("asn_label")["as_name"]
    asn_t.insert(1, "AS name", asn_t["group"].map(names))
    for t, f, cap, lab in [(tp, "top10_provider_primary.tex", "Ten largest infrastructure providers (sibling-merged CAIDA organisations)", "tab:topprov"),
                           (asn_t, "top10_asn_primary.tex", "Ten largest origin ASNs", "tab:topasn")]:
        t2 = t.copy()
        t2["share_attributable"] = (t2["share_attributable"] * 100).round(1)
        t2["cumulative"] = (t2["cumulative"] * 100).round(1)
        t2 = t2.rename(columns={"group": "Group", "nodes": "Nodes", "share_attributable": "Share (%)",
                                "cumulative": "Cum. (%)"})
        to_tex(t2, TAB / f, f"{cap} among functional (NODE\\_WITNESS) IPv4/IPv6 nodes in {primary}.", lab, float_fmt="{:.1f}")

    ctab = class_table(ds)
    ctab.to_csv(TAB / "infra_classes.csv", index=False)
    t = ctab.copy()
    for c in t.columns[2:]:
        t[c] = (t[c] * 100).round(1)
    t = t[["dataset", "nodes", "H1", "H2", "R", "U", "hosted_lower(H1)", "hosted_central(H1+H2)", "hosted_upper(H1+H2+U)"]]
    t.columns = ["Data", "n", "H1", "H2", "R", "U", "Hosted low", "Hosted central", "Hosted high"]
    to_tex(t, TAB / "infra_classes.tex",
           "Infrastructure class of attributable IPv4/IPv6 nodes (\\% of nodes). D3 has no IP addresses, "
           "so H1 (published cloud ranges) cannot be applied there; its cloud nodes fall into H2.",
           "tab:classes", float_fmt="{:.1f}")
    for key, df in ds.items():
        class_reason_table(df).to_csv(TAB / f"infra_class_reasons_{key}.csv", index=False)

    extras = {"geo_vs_rir_agreement": {k: geo_agreement(v) for k, v in ds.items() if not k.startswith("D3")},
              "cross_dataset_overlap_D1_D2": cross_dataset_overlap(ds),
              "cross_dataset_overlap_D1b_D2": cross_dataset_overlap(ds, "D1b"),
              "moas_share": {k: float(v["moas"].mean()) for k, v in ds.items() if "moas" in v},
              "unattributed_asn": {k: int(v["asn"].isna().sum()) for k, v in ds.items()},
              "d2_all_reachable_incl_overlay": d2_all}
    # client software, including Tor/I2P nodes, whose user agent we can see too
    ov = pd.read_csv(PROC / "d2_bitnodes_overlay.csv")
    allc = pd.concat([ds["D2"]["client"], ov["client"]])
    extras["client_D2_all_reachable"] = (allc.value_counts(normalize=True)).round(4).to_dict()
    extras["client_D2_overlay_only"] = ov["client"].value_counts(normalize=True).round(4).to_dict()
    extras["client_hosted_vs_res_D2"] = (ds["D2"].groupby("infra_class")["client"]
                                         .value_counts(normalize=True).round(3).unstack().to_dict(orient="index"))
    (TAB / "extras.json").write_text(json.dumps(extras, indent=2, default=str))

    when = {"D1": "own crawl 2026-10-04", "D2": "Bitnodes/btcnodes snapshot 2026-10-04 09:12 UTC",
            "D3": "KIT DSN dossier 2026-10-03"}[primary]
    base_note = (f"Data: {when}; reachable IPv4/IPv6 nodes signalling NODE_WITNESS, unique IPs. ASN: CAIDA RouteViews pfx2as 2026-09-30; "
                 f"orgs: CAIDA AS2Org 2026-09-01; country: DB-IP Lite 2026-10. Tor/I2P/CJDNS nodes excluded (unattributable).")
    fig_top_bars(p, "geo_cc", f"Observable nodes by country (geolocation), {primary}", "dist_country", base_note)
    fig_top_bars(p, "asn_label", f"Observable nodes by origin ASN, {primary}", "dist_asn", base_note)
    p2 = p.copy()
    fig_top_bars(p2, "provider", f"Observable nodes by infrastructure provider, {primary}", "dist_provider", base_note)
    fig_top_bars(p2, "provider", f"Top-10 infrastructure providers, {primary}", "top10_providers", base_note, n=10)
    fig_cumulative(p, base_note)
    cmp_note = ("NODE_WITNESS nodes only. D1b: own crawl 2026-10-04 (IPv4 from AWS EC2, IPv6 from home vantage); D2: Bitnodes/btcnodes 2026-10-04; D3: KIT DSN 2026-10-03 (KIT whois ASN). "
                "*Country = DB-IP geolocation for D1/D2, AS-registration country for D3. IPv4/IPv6 only.")
    fig_metric_compare(ct, "hhi", "HHI (0-10,000)", "hhi_comparison", "HHI by infrastructure dimension and dataset",
                       cmp_note, ref=1800, ref_label="DOJ/FTC 2023 'highly concentrated' threshold (market context)")
    fig_metric_compare(ct, "gini", "Gini coefficient", "gini_comparison", "Gini coefficient by dimension and dataset", cmp_note)
    fig_classes(ctab, "NODE_WITNESS nodes only. Rules: H1 = IP in provider-published cloud range; H2 = PeeringDB 'Content', curated hosting ASN list "
                      "or hosting keyword; R = APNIC >= 10k users or PeeringDB 'Cable/DSL/ISP'; U = other. D1 home crawl / D1b AWS+home crawl 2026-10-04; D2 Bitnodes 2026-10-04; D3 KIT DSN 2026-10-03.")
    fig_networks(ns, "Data: Bitnodes/btcnodes snapshot 1791105141 (2026-10-04 09:12 UTC). Overlay addresses verified by that crawler.")
    print(ct.to_string())
    print(ctab.to_string())
    print(json.dumps(extras, indent=1, default=str)[:3000])


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
