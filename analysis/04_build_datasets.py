#!/usr/bin/env python3
"""Turns the raw crawler data into clean node tables with infrastructure info.

Writes to data/processed/:
  d1_crawl_nodes.csv       home crawl, one row per reachable IP
  d1_crawl_endpoints.csv   home crawl, one row per IP:port
  d1b_crawl_nodes.csv      AWS crawl (IPv4) plus the home crawl's IPv6 nodes
  d1b_crawl_endpoints.csv  AWS crawl, one row per IP:port
  d2_bitnodes_nodes.csv    Bitnodes, one row per IPv4/IPv6 IP
  d2_bitnodes_overlay.csv  Bitnodes, Tor/I2P/CJDNS nodes
  d3_kit_<stamp>.csv       KIT dossiers, one row per peer (with KIT's own ASN)
  networks_summary.csv     node counts per network type for each dataset
"""
from __future__ import annotations

import glob
import ipaddress
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from lib.attribution import asn_info, attribute  # noqa: E402

RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"


def client_family(ua: str | None) -> str:
    ua = ua if isinstance(ua, str) else ""
    if "Knots" in ua:
        return "Bitcoin Knots"
    if ua.startswith("/Satoshi:"):
        return "Bitcoin Core"
    if not ua:
        return "(empty)"
    return "other"


def is_cjdns(host: str) -> bool:
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("fc00::/8")
    except ValueError:
        return False


def add_functional_flag(df: pd.DataFrame, has_height: bool = True) -> pd.DataFrame:
    """Adds two columns. This filter was added after the pre-registration (see paper).

    functional: True if the node announces NODE_WITNESS. Bitcoin Core only keeps
    outbound full-relay and block-relay peers that do (GetDesirableServiceFlags /
    HasAllDesirableServiceFlags in net_processing.cpp), so nodes without it can't be
    outbound peers of current Core nodes.

    chain_view: where the start height from the version message sits compared to the
    most common height in the snapshot (our stand-in for the SHA256d tip):
      tip           within 6 blocks of it
      below_tip     behind it (still syncing or lagging)
      above_tip     more than 6 blocks ahead
      stalled_961k  between 961,600 and 961,700, where the BIP-110 branch stopped
      zero          height 0
    """
    svc = pd.to_numeric(df["services"], errors="coerce").fillna(0).astype("int64")
    df["functional"] = (svc & 8) != 0
    if has_height:
        h = pd.to_numeric(df["height"], errors="coerce")
        if "t" in df:
            # A crawl takes hours and new blocks arrive in the meantime, so compare each
            # node with the most common height in its own 15-minute window.
            win = (pd.to_numeric(df["t"]) // 900).astype("int64")
            pos = h.where(h > 0)
            tip = pos.groupby(win).transform(lambda s: s.mode().iloc[0] if s.notna().any() else np.nan)
            tip = tip.fillna(pos.mode().iloc[0])
        else:
            tip = h[h > 0].mode().iloc[0]
        view = pd.Series("below_tip", index=df.index)
        view[(h - tip).abs() <= 6] = "tip"
        view[h > tip + 6] = "above_tip"
        view[(h >= 961_600) & (h <= 961_700)] = "stalled_961k"
        view[h == 0] = "zero"
        view[h.isna()] = None
        df["chain_view"] = view
        df["observed_tip"] = tip
    return df


def attribute_frame(df: pd.DataFrame) -> pd.DataFrame:
    att = pd.DataFrame([attribute(ip) for ip in df["ip"]])
    return df.merge(att, on="ip", how="left")


# D1 crawl
def build_crawl(subdir: str = "crawl", prefix: str = "d1", label: str = "D1 own crawl (home)",
                ipv6_from: pd.DataFrame | None = None) -> tuple[dict, pd.DataFrame | None]:
    """Builds the node table for one finished crawl.

    If ipv6_from is given, the crawl's own IPv6 nodes are swapped for those rows.
    We use that for D1b, because the AWS machine had no IPv6.
    """
    files = [f for f in sorted(glob.glob(str(RAW / subdir / "crawl_*[0-9].jsonl")))
             if os.path.exists(f.replace(".jsonl", "_meta.json"))]  # completed crawls only
    if not files:
        print(f"no completed crawl in {subdir}; skipping {label}", file=sys.stderr)
        return {}, None
    path = files[-1]
    meta = json.load(open(path.replace(".jsonl", "_meta.json")))
    recs = [json.loads(l) for l in open(path)]
    df = pd.DataFrame(recs)
    ok = df[df["status"] == "ok"].copy()
    ok = ok[~ok["host"].map(is_cjdns)]
    ok["ip"] = ok["host"]
    ok["client"] = ok["user_agent"].map(client_family)
    ok = ok.sort_values("t")
    endpoints = ok.drop_duplicates(["ip", "port"])
    nodes = endpoints.drop_duplicates("ip").copy()
    nodes = attribute_frame(nodes[["ip", "port", "user_agent", "client", "services", "height", "version", "t"]])
    nodes = add_functional_flag(nodes)
    nodes["vantage"] = subdir
    if ipv6_from is not None:
        nodes = pd.concat([nodes[nodes.ipver == 4], ipv6_from[ipv6_from.ipver == 6]], ignore_index=True)
        endpoints = endpoints[~endpoints["ip"].str.contains(":")]
    nodes.to_csv(PROC / f"{prefix}_crawl_nodes.csv", index=False)
    endpoints[["ip", "port", "user_agent", "client"]].to_csv(PROC / f"{prefix}_crawl_endpoints.csv", index=False)
    overlay = json.load(open(path.replace(".jsonl", "_overlay.json")))
    now = meta["end_utc"]
    fresh = {k: v for k, v in overlay.items() if now - v["first_t"] <= meta["max_addr_age_s"]}
    status = df.drop_duplicates(["host", "port"], keep="last")["status"].value_counts().to_dict()
    return ({"dataset": label, "file": os.path.basename(path),
             "ipv4": int((nodes.ipver == 4).sum()), "ipv6": int((nodes.ipver == 6).sum()),
             "endpoints_ip_port": int(len(endpoints)),
             "onion": sum(1 for v in fresh.values() if v["net"] == "onion"),
             "i2p": sum(1 for v in fresh.values() if v["net"] == "i2p"),
             "cjdns": sum(1 for v in fresh.values() if v["net"] == "cjdns"),
             "overlay_verified": False, "probed": meta["probed_endpoints"],
             "status_counts": json.dumps(status), "start_utc": meta["start_utc"], "end_utc": now},
            nodes)


# D2 Bitnodes
def build_bitnodes(path: Path = RAW / "bitnodes_snapshot_1791105141.json", prefix: str = "d2",
                   label: str = "D2 Bitnodes/btcnodes") -> dict:
    snap = json.load(open(path))
    rows, overlay = [], []
    for key, v in snap["nodes"].items():
        host, port = key.rsplit(":", 1)
        host = host.strip("[]")
        rec = {"ip": host, "port": int(port), "version": v[0], "user_agent": v[1],
               "services": v[3], "height": v[4]}
        if host.endswith(".onion"):
            overlay.append({**rec, "net": "onion"})
        elif host.endswith(".i2p"):
            overlay.append({**rec, "net": "i2p"})
        elif is_cjdns(host):
            overlay.append({**rec, "net": "cjdns"})
        else:
            rows.append(rec)
    df = pd.DataFrame(rows)
    df["client"] = df["user_agent"].map(client_family)
    endpoints = len(df)
    df = df.drop_duplicates("ip")
    df = attribute_frame(df)
    df = add_functional_flag(df)
    df.to_csv(PROC / f"{prefix}_bitnodes_nodes.csv", index=False)
    ov = pd.DataFrame(overlay)
    ov["client"] = ov["user_agent"].map(client_family)
    ov = add_functional_flag(ov)
    ov.to_csv(PROC / f"{prefix}_bitnodes_overlay.csv", index=False)
    return {"dataset": label, "file": path.name,
            "ipv4": int((df.ipver == 4).sum()), "ipv6": int((df.ipver == 6).sum()),
            "endpoints_ip_port": endpoints,
            "onion": int((ov.net == "onion").sum()), "i2p": int((ov.net == "i2p").sum()),
            "cjdns": int((ov.net == "cjdns").sum()), "overlay_verified": True,
            "start_utc": snap["timestamp"], "end_utc": snap["timestamp"]}


# D3 KIT
_ASN_CACHE: dict[int, dict] = {}


def kit_frame(path: str) -> pd.DataFrame:
    d = json.load(open(path))
    rows = []
    for k, v in d.items():
        w = v.get("whois") or {}
        try:
            asn = int(w.get("asn")) if w.get("asn") not in (None, "", "NA") else None
        except ValueError:
            asn = None
        rows.append({"id": k, "ipver": (v.get("ip") or {}).get("version"),
                     "tunnel": (v.get("ip") or {}).get("tunnel"),
                     "asn": asn, "kit_as_name": w.get("name"), "kit_asn_cc": w.get("asn_country_code"),
                     "user_agent": v.get("versionstr"), "services": v.get("services"), "lat": (v.get("geo") or {}).get("lat"),
                     "lon": (v.get("geo") or {}).get("long"), "last_connect": v.get("lastConnect")})
    df = pd.DataFrame(rows)
    df["client"] = df["user_agent"].map(client_family)
    df = add_functional_flag(df, has_height=False)
    for a in df["asn"].dropna().unique():
        a = int(a)
        if a not in _ASN_CACHE:
            _ASN_CACHE[a] = asn_info(a)
    info = pd.DataFrame(list(_ASN_CACHE.values()))
    df["asn"] = df["asn"].astype("Int64")
    info["asn"] = info["asn"].astype("Int64")
    return df.merge(info, on="asn", how="left")


def build_kit() -> list[dict]:
    out = []
    for path in sorted(glob.glob(str(RAW / "kit" / "*_dossier.json"))):
        stamp = os.path.basename(path).split("_dossier")[0]
        df = kit_frame(path)
        df.to_csv(PROC / f"d3_kit_{stamp}.csv", index=False)
        if stamp.startswith("20261003"):
            out.append({"dataset": "D3 KIT DSN", "file": os.path.basename(path),
                        "ipv4": int((df.ipver == 4).sum()), "ipv6": int((df.ipver == 6).sum()),
                        "endpoints_ip_port": None, "onion": None, "i2p": None, "cjdns": None,
                        "overlay_verified": None})
    return out


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    rows = [build_bitnodes()]
    rows += build_kit()
    d1, d1_nodes = build_crawl()
    # D1b is the second crawl, run on an AWS machine without NAT. That machine had no IPv6,
    # so we take its IPv4 nodes and the home crawl's IPv6 nodes (IPv6 at home had no NAT issue).
    d1b, _ = build_crawl("crawl_aws", "d1b", "D1b own crawl (AWS IPv4 + home IPv6)", ipv6_from=d1_nodes)
    for r in (d1b, d1):
        if r:
            rows.insert(0, r)
    # Second day (6 October 2026): the same AWS crawl again (IPv4 only, the machine had no
    # IPv6) and a Bitnodes snapshot taken just before it. Used for the two-day comparison.
    day2 = RAW / "crawl_aws_20261006"
    if day2.exists():
        r2, _ = build_crawl("crawl_aws_20261006", "d1b_20261006", "Day2 D1b AWS crawl (IPv4)")
        rows.append(r2)
        snap2 = sorted(day2.glob("bitnodes_snapshot_*.json"))[-1]
        rows.append(build_bitnodes(snap2, "d2_20261006", "Day2 D2 Bitnodes/btcnodes"))
    pd.DataFrame(rows).to_csv(PROC / "networks_summary.csv", index=False)
    print(pd.DataFrame(rows).to_string())


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
