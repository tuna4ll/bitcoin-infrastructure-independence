#!/usr/bin/env python3
"""Compares the two measurement days (4 and 6 October 2026).

We repeated two of the datasets on 6 October: a Bitnodes snapshot (D2) and our AWS
crawl (D1b, IPv4 only since the machine had no IPv6). For each pair we check whether
the concentration numbers move, how many nodes are seen on both days (split by
hosting class), whether the Linode fleet is still there, and how the nodes on forked
chains developed.

Only the processed tables are used, so this also runs on the pseudonymised public data
(BII_PROCESSED=data/public/processed).

Writes tables/two_days.csv, tables/two_days.tex and tables/two_days.json.
"""
from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from lib import metrics as M  # noqa: E402

PROC, TAB = ROOT / "data" / "processed", ROOT / "tables"
# Set BII_PROCESSED=data/public/processed to run on the pseudonymised public data instead.
PROC = Path(os.environ.get("BII_PROCESSED", PROC))


def is_fleet(df: pd.DataFrame) -> pd.Series:
    return (df["services"] == 3077) & (df["user_agent"] == "/Satoshi:27.0.0/")


def describe(nodes: pd.DataFrame, overlay: pd.DataFrame | None = None) -> dict:
    f = nodes[nodes["functional"]]
    prov = f["provider"].dropna().value_counts()
    out = {
        "ip_nodes": len(nodes), "functional_ip_nodes": len(f),
        "top_provider": prov.index[0], "top_provider_share": M.topk_share(prov, 1),
        "top5_provider_share": M.topk_share(prov, 5),
        "provider_hhi": M.hhi(prov), "provider_n50": M.min_groups_for(prov, 0.5),
        "asn_hhi": M.hhi(f["asn"].dropna().value_counts()),
        "country_hhi": M.hhi(f["geo_cc"].dropna().value_counts()),
        "hosted_central": float(f["infra_class"].isin(["H1", "H2"]).mean()),
        "residential": float((f["infra_class"] == "R").mean()),
        "fleet": int(is_fleet(nodes).sum()),
    }
    allr = pd.concat([nodes, overlay], ignore_index=True) if overlay is not None else nodes
    cv = allr["chain_view"].value_counts()
    n = len(allr)
    out.update({"reachable_hosts": n,
                "above_tip": int(cv.get("above_tip", 0)), "above_tip_share": cv.get("above_tip", 0) / n,
                "stalled_961k": int(cv.get("stalled_961k", 0)), "stalled_share": cv.get("stalled_961k", 0) / n,
                "knots_share": float((allr["client"] == "Bitcoin Knots").mean())})
    return out


def churn(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    """How many day-1 nodes are seen again on day 2, overall and per hosting class."""
    fa, fb = a[a["functional"]], b[b["functional"]]
    sa, sb = set(fa["ip"]), set(fb["ip"])
    out = {"both": len(sa & sb), "only_day1": len(sa - sb), "only_day2": len(sb - sa),
           "jaccard": len(sa & sb) / len(sa | sb), "retained": len(sa & sb) / len(sa)}
    for cls in ["H1", "H2", "R", "U"]:
        ids = set(fa.loc[fa["infra_class"] == cls, "ip"])
        out[f"retained_{cls}"] = len(ids & sb) / len(ids) if ids else float("nan")
    hosted = set(fa.loc[fa["infra_class"].isin(["H1", "H2"]), "ip"])
    out["retained_hosted"] = len(hosted & sb) / len(hosted)
    return out


def main() -> None:
    d2a = pd.read_csv(PROC / "d2_bitnodes_nodes.csv", low_memory=False)
    d2b = pd.read_csv(PROC / "d2_20261006_bitnodes_nodes.csv", low_memory=False)
    ova = pd.read_csv(PROC / "d2_bitnodes_overlay.csv")
    ovb = pd.read_csv(PROC / "d2_20261006_bitnodes_overlay.csv")
    # day 1 of D1b also contains the home crawl's IPv6 nodes, so compare IPv4 only
    awa = pd.read_csv(PROC / "d1b_crawl_nodes.csv", low_memory=False)
    awa = awa[awa["ipver"] == 4]
    awb = pd.read_csv(PROC / "d1b_20261006_crawl_nodes.csv", low_memory=False)
    awb = awb[awb["ipver"] == 4]

    res = {
        "D2": {"day1": describe(d2a, ova), "day2": describe(d2b, ovb), "churn": churn(d2a, d2b)},
        "D1b_v4": {"day1": describe(awa), "day2": describe(awb), "churn": churn(awa, awb)},
    }
    ov_a, ov_b = set(ova["ip"]), set(ovb["ip"])
    res["D2"]["churn"]["overlay_jaccard"] = len(ov_a & ov_b) / len(ov_a | ov_b)
    res["D2"]["churn"]["fleet_both"] = len(set(d2a[is_fleet(d2a)]["ip"]) & set(d2b[is_fleet(d2b)]["ip"]))
    (TAB / "two_days.json").write_text(json.dumps(res, indent=2, default=float))

    rows = []
    for key, lab in [("D2", "Bitnodes (D2)"), ("D1b_v4", "AWS crawl, IPv4 (D1b)")]:
        for day in ["day1", "day2"]:
            r = res[key][day]
            rows.append({"Dataset": lab, "Day": "4 Oct" if day == "day1" else "6 Oct",
                         "IP nodes": r["functional_ip_nodes"],
                         "Top provider": r["top_provider"], "Top %": r["top_provider_share"] * 100,
                         "Top-5 %": r["top5_provider_share"] * 100, "Prov. HHI": r["provider_hhi"],
                         "ASN HHI": r["asn_hhi"], "Country HHI": r["country_hhi"],
                         "Hosted %": r["hosted_central"] * 100})
    t = pd.DataFrame(rows)
    t.to_csv(TAB / "two_days.csv", index=False)
    t2 = t.copy()
    for c in ["Prov. HHI", "ASN HHI", "Country HHI"]:
        t2[c] = t2[c].round(0).astype(int)
    import_module("05_concentration").to_tex(
        t2, TAB / "two_days.tex",
        "The same measurements on 4 and 6 October 2026 (functional IPv4/IPv6 nodes for D2, functional "
        "IPv4 nodes for the AWS crawl). Hosted \\% is the central estimate H1+H2.",
        "tab:twodays", colfmt="llrlrrrrrr", float_fmt="{:.1f}")
    print(t.round(2).to_string())
    print(json.dumps({k: v["churn"] for k, v in res.items()}, indent=1))
    print({k: (res[k]["day1"]["above_tip"], res[k]["day2"]["above_tip"], res[k]["day1"]["stalled_961k"],
               res[k]["day2"]["stalled_961k"], res[k]["day1"]["fleet"], res[k]["day2"]["fleet"]) for k in res})


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
