#!/usr/bin/env python3
"""How infrastructure diversity changed from 2015 to 2026 (KIT DSN dossiers).

We use the ASN that KIT recorded at the time of each measurement, so old data is
not re-mapped with today's routing table. Organisation names and the hosting
classification do come from 2026 sources though (CAIDA AS2Org, PeeringDB, APNIC).
An AS that changed owner or business over the years is therefore classified by
what it is today. The paper mentions this.
"""
from __future__ import annotations

import glob
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


def row(path: str) -> dict:
    stamp = os.path.basename(path)[len("d3_kit_"):-4]
    df = pd.read_csv(path, low_memory=False)
    a = df.dropna(subset=["asn"])
    asn_c = a["asn"].value_counts()
    prov_c = a["provider"].value_counts()
    cc_c = df["kit_asn_cc"].dropna().value_counts()
    return {
        "date": pd.to_datetime(stamp[:8]), "stamp": stamp, "peers": len(df),
        "ipv6_share": float((df["ipver"] == 6).mean()),
        "asns": len(asn_c), "asn_hhi": M.hhi(asn_c), "asn_top1": M.topk_share(asn_c, 1),
        "asn_top10": M.topk_share(asn_c, 10), "asn_gini": M.gini(asn_c),
        "asn_nakamoto50": M.min_groups_for(asn_c, 0.5),
        "provider_hhi": M.hhi(prov_c), "provider_top1_label": prov_c.index[0],
        "provider_top1": M.topk_share(prov_c, 1), "provider_top5": M.topk_share(prov_c, 5),
        "hosted_share_asn_level": float(a["infra_class"].isin(["H2"]).mean()),
        "residential_share_asn_level": float((a["infra_class"] == "R").mean()),
        "countries": len(cc_c), "country_hhi": M.hhi(cc_c), "country_top1_label": cc_c.index[0],
        "country_top1": M.topk_share(cc_c, 1),
        "knots_share": float((df["client"] == "Bitcoin Knots").mean()),
        "non_witness_share": float((~df["functional"]).mean()),
    }


def main() -> None:
    files = sorted(glob.glob(str(PROC / "d3_kit_*.csv")))
    ts = pd.DataFrame([row(f) for f in files]).sort_values("date")
    ts.to_csv(TAB / "timeseries_kit.csv", index=False)
    annual = ts[ts["stamp"].str[4:8].isin(["1001", "1002"])].groupby(ts["date"].dt.year).head(1).copy()
    recent = ts[ts["date"] >= "2026-09-27"]
    stab = recent[["asn_hhi", "asn_top10", "provider_hhi", "provider_top1", "hosted_share_asn_level",
                   "country_hhi"]].agg(["min", "max", "mean"]).T
    stab["range_rel_to_mean"] = (stab["max"] - stab["min"]) / stab["mean"]
    stab.to_csv(TAB / "kit_7day_stability.csv")

    t = annual[["date", "peers", "asns", "asn_hhi", "asn_top10", "provider_top1_label", "provider_top1",
                "hosted_share_asn_level", "country_top1_label", "country_top1", "knots_share"]].copy()
    t["date"] = t["date"].dt.strftime("%Y-%m-%d")
    for c in ["asn_top10", "provider_top1", "hosted_share_asn_level", "country_top1", "knots_share"]:
        t[c] = (t[c] * 100).round(1)
    t["asn_hhi"] = t["asn_hhi"].round(0).astype(int)
    t.columns = ["Date", "Peers", "ASNs", "ASN HHI", "Top-10 ASN %", "Top provider", "%", "Hosted %",
                 "Top AS-cc", "%", "Knots %"]
    from importlib import import_module
    import_module("05_concentration").to_tex(
        t, TAB / "timeseries_kit.tex",
        "Infrastructure diversity of peers in KIT DSN dossiers (1 October of each year, IPv4/IPv6). "
        "Hosted \\% = share of peers in ASNs classified as hosting (H2) with 2026 classification sources.",
        "tab:timeseries", colfmt="lrrrrlrrlrr", float_fmt="{:.1f}")

    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.8))
    ax = axes[0]
    ax.plot(annual["date"], annual["asn_hhi"], color=SERIES[0], marker="o", ms=4, label="ASN")
    ax.plot(annual["date"], annual["provider_hhi"], color=SERIES[1], marker="o", ms=4, label="Provider (merged)")
    ax.set_ylabel("HHI")
    ax.set_title("Concentration (HHI)")
    ax.set_ylim(0, 500)
    ax.legend(fontsize=6.5, loc="lower center", ncol=2)
    ax = axes[1]
    ax.plot(annual["date"], annual["hosted_share_asn_level"] * 100, color=SERIES[0], marker="o", ms=4,
            label="Hosting ASNs (H2)")
    ax.plot(annual["date"], annual["residential_share_asn_level"] * 100, color=SERIES[1], marker="o", ms=4,
            label="Access/residential ASNs (R)")
    ax.set_ylabel("Share of peers (%)")
    ax.set_ylim(0, 80)
    ax.set_title("Infrastructure class")
    ax.legend(fontsize=6.5, loc="lower center", ncol=1)
    for a in axes:
        a.tick_params(axis="x", labelsize=7)
    fig.suptitle("Infrastructure diversity over time (KIT DSN, 1 Oct each year)", x=0.0, ha="left",
                 fontsize=10, fontweight="bold")
    fig.tight_layout()
    source_note(fig, "Data: KIT DSN Bitcoin monitor dossiers 2015-10-01 ... 2026-10-01 (KIT whois ASN at measurement "
                     "time). Organisation and class mapping use 2026 sources (anachronism risk).")
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"diversity_over_time.{ext}")
    plt.close(fig)
    print(t.to_string())
    print(stab.to_string())


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
