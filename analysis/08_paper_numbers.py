#!/usr/bin/env python3
"""Writes every number used in the paper as a LaTeX macro.

paper.tex reads paper/numbers.tex, so no number in the text is typed by hand.
This script also writes the chain-view table (tables/chain_view.tex).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
PROC, TAB, RAW, PAPER = ROOT / "data" / "processed", ROOT / "tables", ROOT / "data" / "raw", ROOT / "paper"
# Set BII_PROCESSED=data/public/processed to run on the pseudonymised public data instead.
PROC = Path(os.environ.get("BII_PROCESSED", PROC))
to_tex = import_module("05_concentration").to_tex

M: dict[str, str] = {}


def name(s: str) -> str:
    """LaTeX macro names can only contain letters, so digits are spelled out."""
    digits = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six",
              "7": "Seven", "8": "Eight", "9": "Nine"}
    s = "".join(digits.get(c, c) for c in s)
    return re.sub(r"[^A-Za-z]", "", s)


def put(key: str, val, kind: str = "int") -> None:
    if kind == "int":
        v = f"{int(round(val)):,}".replace(",", "{,}")
    elif kind == "pct":
        x = val * 100
        if x == 0:
            v = "0\\%"
        elif x < 0.01:
            v = "$<$0.01\\%"
        elif x < 1:
            v = f"{x:.2f}\\%"
        elif 99.9 < x < 100:
            v = f"{x:.2f}\\%" if x < 99.995 else "$>$99.99\\%"
        else:
            v = f"{x:.1f}\\%"
    elif kind == "pct0":
        v = f"{val * 100:.0f}\\%"
    elif kind.startswith("f"):
        v = f"{val:.{int(kind[1:])}f}"
    else:
        v = str(val).replace("&", "\\&").replace("_", "\\_")
    M[name(key)] = v


def main() -> None:
    ns = pd.read_csv(PROC / "networks_summary.csv")
    d1m = ns[ns.dataset.str.startswith("D1 ")].iloc[0]
    d1bm = ns[ns.dataset.str.startswith("D1b")].iloc[0]
    d2m = ns[ns.dataset.str.startswith("D2")].iloc[0]
    d1 = pd.read_csv(PROC / "d1_crawl_nodes.csv", low_memory=False)
    d2 = pd.read_csv(PROC / "d2_bitnodes_nodes.csv", low_memory=False)
    ov = pd.read_csv(PROC / "d2_bitnodes_overlay.csv")
    d3 = pd.read_csv(sorted(glob.glob(str(PROC / "d3_kit_20261003_*.csv")))[-1], low_memory=False)

    ex = json.load(open(TAB / "extras.json"))
    # populations
    allr = len(d2) + len(ov)
    put("DtwoEndpoints", 25139)  # snapshot header 'total_nodes'
    put("DtwoHosts", allr)
    put("DtwoIPvfour", (d2.ipver == 4).sum()); put("DtwoIPvsix", (d2.ipver == 6).sum())
    put("DtwoIP", len(d2)); put("DtwoIPshare", len(d2) / allr, "pct")
    for net in ["onion", "i2p", "cjdns"]:
        put(f"Dtwo{net}", (ov.net == net).sum())
    put("DtwoOverlayShare", len(ov) / allr, "pct")
    put("DtwoTorShare", (ov.net == "onion").sum() / allr, "pct")
    put("DoneIP", len(d1)); put("DoneIPvfour", (d1.ipver == 4).sum()); put("DoneIPvsix", (d1.ipver == 6).sum())
    put("DoneProbed", d1m.probed); put("DoneOnion", d1m.onion); put("DoneItwop", d1m.i2p)
    meta = json.load(open(sorted(glob.glob(str(RAW / "crawl" / "crawl_*_meta.json")))[-1]))
    put("DoneHours", (meta["end_utc"] - meta["start_utc"]) / 3600, "f1")
    put("DoneGossip", meta["gossip_ip_total"]); put("DoneSeeds", meta["seed_endpoints"])
    put("DoneRetried", meta["retried_timeouts"])
    put("DthreeIP", len(d3)); put("DthreeIPvfour", (d3.ipver == 4).sum()); put("DthreeIPvsix", (d3.ipver == 6).sum())
    # D1b: AWS crawl for IPv4, home crawl for IPv6
    d1b = pd.read_csv(PROC / "d1b_crawl_nodes.csv", low_memory=False)
    mb = json.load(open(sorted(glob.glob(str(RAW / "crawl_aws" / "crawl_*_meta.json")))[-1]))
    put("DonebIP", len(d1b)); put("DonebIPvfour", (d1b.ipver == 4).sum()); put("DonebIPvsix", (d1b.ipver == 6).sum())
    put("DonebProbed", mb["probed_endpoints"]); put("DonebHours", (mb["end_utc"] - mb["start_utc"]) / 3600, "f1")
    put("DonebRetried", mb["retried_timeouts"]); put("DonebConc", mb["concurrency"])
    put("DonebOnion", d1bm.onion); put("DonebItwop", d1bm.i2p)
    put("DonebFunctional", d1b.functional.sum())
    d1bcv = d1b[d1b.ipver == 4].chain_view.value_counts()
    put("DonebAbove", d1bcv.get("above_tip", 0)); put("DonebStalled", d1bcv.get("stalled_961k", 0))
    d2v4 = set(d2[d2.ipver == 4].ip); b4 = set(d1b[d1b.ipver == 4].ip)
    put("AwsCoverDtwoVfour", len(d2v4 & b4) / len(d2v4), "pct"); put("AwsOnlyVfour", len(b4 - d2v4))
    put("HomeCoverDtwoVfour", len(d2v4 & set(d1[d1.ipver == 4].ip)) / len(d2v4), "pct")
    ovb = ex["cross_dataset_overlap_D1b_D2"]
    put("OverlapbBoth", ovb["both"]); put("OverlapbOnlyDone", ovb["only_D1"]); put("OverlapbOnlyDtwo", ovb["only_D2"])
    put("OverlapbJaccard", ovb["jaccard"], "f2")
    rp = json.load(open(sorted(glob.glob(str(RAW / "crawl" / "reprobe_*_meta.json")))[-1]))
    put("ReprobeTargets", rp["targets"]); put("ReprobeOK", rp["status"].get("ok", 0))
    put("ReprobeShare", rp["status"].get("ok", 0) / rp["targets"], "pct")
    ov12 = ex["cross_dataset_overlap_D1_D2"]
    put("OverlapBoth", ov12["both"]); put("OverlapOnlyDone", ov12["only_D1"]); put("OverlapOnlyDtwo", ov12["only_D2"])
    put("OverlapJaccard", ov12["jaccard"], "f2")

    # anomalous fleet
    fleet = (d2.services == 3077) & (d2.user_agent == "/Satoshi:27.0.0/")
    put("FleetN", fleet.sum()); put("FleetShareIP", fleet.sum() / len(d2), "pct")
    put("FleetLinode", (fleet & (d2.provider == "Akamai/Linode")).sum())
    put("FleetSubnets", d2[fleet].subnet.nunique()); put("FleetNetgroups", d2[fleet].netgroup.nunique())
    put("FleetHzero", (d2[fleet].height == 0).sum())
    kit_raw = json.load(open(RAW / "kit" / "20261003_121755_dossier.json"))
    put("FleetKIT", sum(1 for v in kit_raw.values() if v.get("services") == 3077 and v.get("versionstr") == "/Satoshi:27.0.0/"))
    crawl_files = sorted(glob.glob(str(RAW / "crawl" / "crawl_*[0-9].jsonl")))
    if crawl_files and not (PROC / "raw_derived.json").exists():
        r = pd.DataFrame([json.loads(l) for l in open(crawl_files[-1])])
        put("FleetDoneSeen", d2[fleet].ip.isin(set(r.host)).sum())
    else:  # public release: raw crawl (with IPs) is not distributed
        put("FleetDoneSeen", json.load(open(PROC / "raw_derived.json"))["fleet_seen_by_d1"])
    aws_files = sorted(glob.glob(str(RAW / "crawl_aws" / "crawl_*[0-9].jsonl")))
    if aws_files and not (PROC / "raw_derived.json").exists():
        ra = pd.DataFrame([json.loads(l) for l in open(aws_files[-1])])
        put("FleetAwsSeen", d2[fleet].ip.isin(set(ra.host)).sum())
        put("FleetAwsOK", d2[fleet].ip.isin(set(ra[ra.status == "ok"].host)).sum())
    else:
        rd = json.load(open(PROC / "raw_derived.json"))
        put("FleetAwsSeen", rd["fleet_seen_by_d1b"]); put("FleetAwsOK", rd["fleet_ok_in_d1b"])
    put("DtwoNonWitness", (~d2.functional).sum()); put("DtwoFunctional", d2.functional.sum())
    put("DthreeFunctional", d3.functional.sum()); put("DoneFunctional", d1.functional.sum())

    # chain views (all reachable D2 nodes including Tor/I2P, plus our crawls)
    a = pd.concat([d2.assign(net="ip"), ov], ignore_index=True)
    cv = pd.crosstab(a.chain_view, a.client)
    cv["Total"] = cv.sum(axis=1)
    cv["Share"] = cv["Total"] / cv["Total"].sum()
    order = ["tip", "below_tip", "above_tip", "stalled_961k", "zero"]
    cv = cv.reindex(order)
    for k in order:
        put(f"Chain{k}", cv.loc[k, "Total"]); put(f"Chain{k}Share", cv.loc[k, "Share"], "pct")
    put("ForkShareAll", (cv.loc["above_tip", "Total"] + cv.loc["stalled_961k", "Total"]) / cv["Total"].sum(), "pct")
    put("ChainAboveKnots", cv.loc["above_tip", "Bitcoin Knots"]); put("ChainStalledKnots", cv.loc["stalled_961k", "Bitcoin Knots"])
    put("ObservedTip", int(d2.observed_tip.iloc[0]))
    above = a[a.chain_view == "above_tip"].height - d2.observed_tip.iloc[0]
    put("AboveMedian", above.median()); put("StalledMedian", a[a.chain_view == "stalled_961k"].height.median())
    put("KnotsShareAll", (a.client == "Bitcoin Knots").mean(), "pct")
    put("KnotsShareOverlay", (ov.client == "Bitcoin Knots").mean(), "pct")
    put("KnotsShareR", (d2[d2.infra_class == "R"].client == "Bitcoin Knots").mean(), "pct")
    put("KnotsShareHone", (d2[d2.infra_class == "H1"].client == "Bitcoin Knots").mean(), "pct")
    # do nodes on forked chains run at the same providers as main-chain nodes?
    fn = d2[d2.functional]
    fork = fn[fn.chain_view.isin(["above_tip", "stalled_961k"])]
    main_ = fn[fn.chain_view.isin(["tip", "below_tip"])]
    put("ForkIP", len(fork)); put("ForkProvTotal", fork.provider.nunique())
    put("ForkProvBoth", len(set(fork.provider) & set(main_.provider)))
    put("ForkInTopTen", fork.provider.isin(main_.provider.value_counts().index[:10]).sum())
    put("ForkResid", (fork.infra_class == "R").mean(), "pct"); put("MainResid", (main_.infra_class == "R").mean(), "pct")
    d1cv = d1.chain_view.value_counts()
    put("DoneAbove", d1cv.get("above_tip", 0)); put("DoneStalled", d1cv.get("stalled_961k", 0))
    t = cv.reset_index().rename(columns={"chain_view": "Height relative to SHA256d tip"})
    t["Share"] = (t["Share"] * 100).round(1)
    t["Height relative to SHA256d tip"] = t["Height relative to SHA256d tip"].map({
        "tip": "at tip ($\\pm$6 blocks)", "below_tip": "below tip (lagging/syncing)",
        "above_tip": "above tip ($>$6 blocks)", "stalled_961k": "961{,}600--961{,}700",
        "zero": "zero"})
    cols = [c for c in ["Height relative to SHA256d tip", "Bitcoin Core", "Bitcoin Knots", "other", "Total", "Share"] if c in t]
    t = t[cols].rename(columns={"Share": "Share (%)"})
    path = TAB / "chain_view.tex"
    to_tex(t, path, "Start height reported in the version handshake by all reachable nodes in D2 "
                    "(IPv4, IPv6, Tor, I2P, CJDNS; unique hosts), relative to the modal height of the snapshot.",
           "tab:chainview", colfmt="lrrrrr", float_fmt="{:.1f}")
    path.write_text(path.read_text().replace("\\$", "$").replace("\\textbackslash{}", "\\"))

    # concentration, for all nodes and for NODE_WITNESS nodes only
    ct = pd.read_csv(TAB / "concentration_summary.csv")

    def c(ds, dim, col):
        return ct[(ct.dataset == ds) & (ct.dimension == dim)][col].iloc[0]

    for ds in ["D1", "D1b", "D2", "D3", "D1f", "D1bf", "D2f", "D3f"]:
        k = ds.replace("1", "one").replace("2", "two").replace("3", "three").replace("f", "F")
        for dim, tag in [("ASN", "Asn"), ("Provider (sibling-merged)", "Prov"), ("Organisation (CAIDA AS2Org)", "Org")]:
            put(f"{k}{tag}Groups", c(ds, dim, "groups"))
            put(f"{k}{tag}Topone", c(ds, dim, "top1_share"), "pct")
            put(f"{k}{tag}ToponeLabel", c(ds, dim, "top1_label"), "str")
            put(f"{k}{tag}Topfive", c(ds, dim, "top5_share"), "pct")
            put(f"{k}{tag}Topten", c(ds, dim, "top10_share"), "pct")
            put(f"{k}{tag}HHI", c(ds, dim, "hhi"))
            put(f"{k}{tag}Neff", c(ds, dim, "effective_groups"), "f1")
            put(f"{k}{tag}Gini", c(ds, dim, "gini"), "f2")
            put(f"{k}{tag}Nfifty", c(ds, dim, "nakamoto_50"))
            put(f"{k}{tag}Nthird", c(ds, dim, "nakamoto_33"))
        cdim = "Country (AS registration, KIT whois)" if ds.startswith("D3") else "Country (geolocation, DB-IP)"
        put(f"{k}CcGroups", c(ds, cdim, "groups")); put(f"{k}CcTopone", c(ds, cdim, "top1_share"), "pct")
        put(f"{k}CcToponeLabel", c(ds, cdim, "top1_label"), "str")
        put(f"{k}CcTopfive", c(ds, cdim, "top5_share"), "pct"); put(f"{k}CcHHI", c(ds, cdim, "hhi"))
        put(f"{k}CcNfifty", c(ds, cdim, "nakamoto_50")); put(f"{k}CcGini", c(ds, cdim, "gini"), "f2")
        if not ds.startswith("D3"):
            r_ = "Country (RIR registration)"
            put(f"{k}RirTopone", c(ds, r_, "top1_share"), "pct"); put(f"{k}RirHHI", c(ds, r_, "hhi"))
            put(f"{k}SubnetGroups", c(ds, "IPv4 /24 | IPv6 /48 subnet", "groups"))
            put(f"{k}SubnetTopone", c(ds, "IPv4 /24 | IPv6 /48 subnet", "top1_share"), "pct")
        put(f"{k}ClientHHI", c(ds, "Client software", "hhi"))
        put(f"{k}CoreShare", c(ds, "Client software", "top1_share"), "pct")

    cl = pd.read_csv(TAB / "infra_classes.csv").set_index("dataset")
    for ds in cl.index:
        k = ds.replace("1", "one").replace("2", "two").replace("3", "three").replace("f", "F")
        for col in ["H1", "H2", "R", "U"]:
            put(f"{k}Class{col}", cl.loc[ds, col], "pct")
        put(f"{k}HostedLow", cl.loc[ds, "hosted_lower(H1)"], "pct")
        put(f"{k}HostedCentral", cl.loc[ds, "hosted_central(H1+H2)"], "pct")
        put(f"{k}HostedHigh", cl.loc[ds, "hosted_upper(H1+H2+U)"], "pct")
    reasons = pd.read_csv(TAB / "infra_class_reasons_D2f.csv")
    rx = reasons[reasons.class_reason == "name-regex"]["nodes"].sum()
    put("RegexNodes", rx); put("RegexShare", rx / cl.loc["D2f", "nodes"], "pct")
    ga = ex["geo_vs_rir_agreement"]
    put("GeoAgree", ga["D2f"]["agreement"], "pct"); put("GeoAgreeHone", ga["D2f"]["agree_H1"], "pct")
    put("GeoAgreeR", ga["D2f"]["agree_R"], "pct"); put("MoasShare", ex["moas_share"]["D2f"], "pct")
    # top providers D2f
    tp = pd.read_csv(TAB / "top10_provider_D2f.csv")
    for i in range(5):
        put(f"Prov{['One','Two','Three','Four','Five'][i]}Name", tp.group[i], "str")
        put(f"Prov{['One','Two','Three','Four','Five'][i]}Share", tp.share_attributable[i], "pct")
    tcc = pd.read_csv(TAB / "top10_country_D2f.csv")
    put("CcTopTwo", tcc.share_attributable[:2].sum(), "pct")
    for i in range(3):
        put(f"Cc{['One','Two','Three'][i]}Name", tcc.group[i], "str")
        put(f"Cc{['One','Two','Three'][i]}Share", tcc.share_attributable[i], "pct")

    # Luke Dashjr estimate
    luke = json.load(open(RAW / "luke_uainfo.json"))
    L = sum(v.get("listening", 0) for v in luke.values()); U = sum(v.get("est_unreachable", 0) for v in luke.values())
    put("LukeListening", L); put("LukeUnreach", U); put("LukeTotal", L + U); put("LukeUnreachShare", U / (L + U), "pct")
    put("ReachOfLukeTotal", allr / (allr + U), "pct")
    put("AttribOfTotal", len(d2) / (allr + U), "pct")

    # time series
    ts = pd.read_csv(TAB / "timeseries_kit.csv", parse_dates=["date"])
    ann = ts[ts.stamp.str[4:8].isin(["1001", "1002"])].sort_values("date")
    ann = ann.groupby(ann.date.dt.year).head(1)
    ann = ann.set_index(ann.date.dt.year)
    for y in [2015, 2020, 2026]:
        yy = {2015: "Fifteen", 2020: "Twenty", 2026: "TwentySix"}[y]
        put(f"TS{yy}AsnHHI", ann.loc[y, "asn_hhi"]); put(f"TS{yy}Hosted", ann.loc[y, "hosted_share_asn_level"], "pct")
        put(f"TS{yy}Topten", ann.loc[y, "asn_top10"], "pct"); put(f"TS{yy}Peers", ann.loc[y, "peers"])
        put(f"TS{yy}ProvTop", ann.loc[y, "provider_top1"], "pct"); put(f"TS{yy}ProvTopLabel", ann.loc[y, "provider_top1_label"], "str")
        put(f"TS{yy}Knots", ann.loc[y, "knots_share"], "pct"); put(f"TS{yy}Resid", ann.loc[y, "residential_share_asn_level"], "pct")
    peak = ann.asn_hhi.idxmax(); put("TSPeakYear", int(peak), "str"); put("TSPeakHHI", ann.asn_hhi.max())
    put("TSPeakHosted", ann.hosted_share_asn_level.max(), "pct"); put("TSPeakHostedYear", int(ann.hosted_share_asn_level.idxmax()), "str")
    st = pd.read_csv(TAB / "kit_7day_stability.csv", index_col=0)
    put("StabMaxRel", st["range_rel_to_mean"].max(), "pct")

    # failure scenarios
    fs = pd.read_csv(TAB / "failure_static.csv").set_index("scenario")
    fm = json.load(open(TAB / "failure_meta.json"))
    put("FailIP", fm["ip_nodes"]); put("FailOverlay", sum(fm["overlay_nodes"].values()))
    put("InboundCap", fm["inbound_cap"]); put("InboundCapMaster", fm.get("inbound_cap_master", 189))
    for idx, key in [(1, "Asn"), (2, "Prov"), (3, "Cc"), (4, "Topfive"), (5, "Topten"), (6, "Hosted")]:
        row = fs.iloc[idx]
        put(f"Fail{key}Label", fs.index[idx], "str")
        put(f"Fail{key}Lost", row.nodes_lost)
        put(f"Fail{key}IP", row.share_of_ip_reachable, "pct")
        put(f"Fail{key}All", row.share_of_all_reachable, "pct")
        put(f"Fail{key}A", row.share_of_all_incl_unreachable_A, "pct")
        put(f"Fail{key}B", row.share_of_all_incl_unreachable_B, "pct")
        put(f"Fail{key}Asns", row.remaining_asns); put(f"Fail{key}Ccs", row.remaining_countries)
    put("FailMinAsns", fs.remaining_asns.min()); put("FailMinCcs", fs.remaining_countries.min())
    if (TAB / "failure_model_summary.csv").exists():
        sm = pd.read_csv(TAB / "failure_model_summary.csv")
        g = sm[(sm["mode"] == "netgroup") & sm.dual_stack.str.contains("25")]
        for pop, pk in [("reachable only", "R"), ("with non-listening est.", "U")]:
            gg = g[g.population == pop].set_index("scenario")
            base = gg.iloc[0]
            put(f"Mod{pk}BaseHops", base.now_mean_hops_all, "f2"); put(f"Mod{pk}BaseFullHops", base.now_mean_hops_full, "f2")
            put(f"Mod{pk}BaseInbound", base.now_mean_inbound, "f1"); put(f"Mod{pk}BaseMaxInbound", base.now_max_inbound)
            hz = gg.loc["All hosted (H1+H2)"]
            put(f"Mod{pk}HostedZero", hz.now_zero_outbound, "pct"); put(f"Mod{pk}HostedZeroFull", hz.now_zero_full_relay, "pct")
            put(f"Mod{pk}HostedLCC", hz.now_lcc, "pct"); put(f"Mod{pk}HostedHops", hz.now_mean_hops_all, "f2")
            put(f"Mod{pk}HostedHopsAfter", hz.after_mean_hops_all, "f2")
            put(f"Mod{pk}HostedInbound", hz.after_mean_inbound, "f1"); put(f"Mod{pk}HostedMaxInbound", hz.after_max_inbound)
            put(f"Mod{pk}HostedOverCap", hz.after_share_reachable_over_cap, "pct")
            tf = gg.loc["Top-5 providers"]
            put(f"Mod{pk}TopfiveZero", tf.now_zero_outbound, "pct"); put(f"Mod{pk}TopfiveLCC", tf.now_lcc, "pct")
            put(f"Mod{pk}TopfiveHops", tf.now_mean_hops_all, "f2")
            mz = gg.now_zero_outbound.max(); put(f"Mod{pk}MaxZero", mz, "pct")
            put(f"Mod{pk}BaseOverCap", base.after_share_reachable_over_cap, "pct")
            put(f"Mod{pk}BaseOverCapNow", base.now_share_reachable_over_cap, "pct")
            put(f"Mod{pk}BasePninetynine", base.now_p99_inbound, "f0")
            put(f"Mod{pk}HostedOverCapMaster", hz.after_share_reachable_over_cap_master, "pct")
            put(f"Mod{pk}TopfiveOverCapMaster", tf.after_share_reachable_over_cap_master, "pct")
            put(f"Mod{pk}ProvOverCapMaster", gg.iloc[2].after_share_reachable_over_cap_master, "pct")
            put(f"Mod{pk}CcOverCapMaster", gg.iloc[3].after_share_reachable_over_cap_master, "pct")
            put(f"Mod{pk}BaseOverCapMaster", base.after_share_reachable_over_cap_master, "pct")
            put(f"Mod{pk}ProvOverCap", gg.iloc[2].after_share_reachable_over_cap, "pct")
            put(f"Mod{pk}ProvInbound", gg.iloc[2].after_mean_inbound, "f1")
            put(f"Mod{pk}TopfiveOverCap", tf.after_share_reachable_over_cap, "pct")
            put(f"Mod{pk}CcOverCap", gg.iloc[3].after_share_reachable_over_cap, "pct")
            put(f"Mod{pk}MinLCC", gg.now_lcc.min(), "pct")
        g0 = sm[(sm["mode"] == "netgroup") & sm.dual_stack.str.contains("0%") & ~sm.dual_stack.str.contains("25")]
        if len(g0):
            hz0 = g0[g0.scenario == "All hosted (H1+H2)"].iloc[0]
            put("ModZeroDualHostedLCC", hz0.now_lcc, "pct"); put("ModZeroDualHostedZero", hz0.now_zero_outbound, "pct")
            put("ModZeroDualBaseLCC", g0.iloc[0].now_lcc, "pct")
        ecl = pd.read_csv(TAB / "eclipse_exposure.csv")
        for mode, mk in [("netgroup", "Ng"), ("asmap", "As")]:
            e = ecl[(ecl["mode"] == mode) & (ecl.population == "with non-listening est.")].mean(numeric_only=True)
            put(f"Ecl{mk}All", e.all_clearnet_outbound_one_provider, "pct")
            put(f"Ecl{mk}Maj", e.majority_clearnet_outbound_one_provider, "pct")
            put(f"Ecl{mk}MeanMax", e.mean_max_provider_share, "pct")
            put(f"Ecl{mk}TopHalf", e.ge50pct_full_relay_in_top_provider, "pct")
        put("EclTop", ecl.top_provider.iloc[0], "str")

    # second measurement day (from 10_two_days.py)
    if (TAB / "two_days.json").exists():
        td = json.load(open(TAB / "two_days.json"))
        for key, k in [("D2", "TdDtwo"), ("D1b_v4", "TdAws")]:
            for day, dk in [("day1", "A"), ("day2", "B")]:
                r = td[key][day]
                put(f"{k}{dk}Nodes", r["functional_ip_nodes"]); put(f"{k}{dk}Top", r["top_provider_share"], "pct")
                put(f"{k}{dk}TopLabel", r["top_provider"], "str"); put(f"{k}{dk}ProvHHI", r["provider_hhi"])
                put(f"{k}{dk}AsnHHI", r["asn_hhi"]); put(f"{k}{dk}CcHHI", r["country_hhi"])
                put(f"{k}{dk}Hosted", r["hosted_central"], "pct"); put(f"{k}{dk}Fleet", r["fleet"])
                put(f"{k}{dk}Above", r["above_tip"]); put(f"{k}{dk}Stalled", r["stalled_961k"])
                put(f"{k}{dk}Knots", r["knots_share"], "pct")
            c = td[key]["churn"]
            put(f"{k}Retained", c["retained"], "pct"); put(f"{k}Jaccard", c["jaccard"], "f2")
            put(f"{k}RetHosted", c["retained_hosted"], "pct"); put(f"{k}RetR", c["retained_R"], "pct")
            put(f"{k}RetHOne", c["retained_H1"], "pct"); put(f"{k}RetHTwo", c["retained_H2"], "pct")
            put(f"{k}OnlyA", c["only_day1"]); put(f"{k}OnlyB", c["only_day2"])
        put("TdOverlayJaccard", td["D2"]["churn"]["overlay_jaccard"], "f2")
        put("TdFleetBoth", td["D2"]["churn"]["fleet_both"])
        hh = [td[k][d]["provider_hhi"] for k in ["D2", "D1b_v4"] for d in ["day1", "day2"]]
        put("TdMaxProvHHIChange", max(abs(td[k]["day1"]["provider_hhi"] - td[k]["day2"]["provider_hhi"])
                                       for k in ["D2", "D1b_v4"]))

    # inbound capacity (from 06b_capacity.py)
    cu = pd.read_csv(TAB / "capacity_unmet_summary.csv")
    cu = cu[cu.population == "with non-listening est."]
    for cap, ck in [("released (114)", "Rel"), ("master (189)", "Mas")]:
        cc = cu[cu.capacity == cap].set_index("scenario")
        for i, sk in enumerate(["Base", "Asn", "Prov", "Cc", "Topfive", "Topten", "Hosted"]):
            put(f"Unmet{ck}{sk}", cc.iloc[i].unmet_share_all, "pct")
    rel = cu[cu.capacity == "released (114)"].set_index("scenario")
    put("UnmetRelTopfiveDelta", (rel.loc["Top-5 providers"].unmet_share_all - rel.iloc[0].unmet_share_all) * 100, "f0")
    put("UnmetReachOnlyMax", pd.read_csv(TAB / "capacity_unmet_summary.csv").query(
        "population == 'reachable only'").unmet_share_all.max(), "pct")

    # Bitcoin Core commit
    put("CoreCommit", (RAW / "bitcoin-core" / "COMMIT").read_text().strip()[:10], "str")

    lines = ["% Auto-generated by analysis/08_paper_numbers.py -- do not edit by hand."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(M.items())]
    (PAPER / "numbers.tex").write_text("\n".join(lines) + "\n")
    print(f"{len(M)} macros written")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
