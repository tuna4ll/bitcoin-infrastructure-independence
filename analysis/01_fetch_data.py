#!/usr/bin/env python3
"""Downloads every external dataset the study uses.

Each file is logged in data/raw/MANIFEST.csv with its URL, download time (UTC),
size and SHA-256 hash, so you can always tell which inputs a result came from.
Files that are already on disk are skipped. That matters here because some
sources are rate limited (the Bitnodes/btcnodes API allows only 10 requests per
IP per day).

Run: python analysis/01_fetch_data.py
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "MANIFEST.csv"
UA = {"User-Agent": "bitcoin-infrastructure-independence research (academic measurement)"}

KIT_BASE = "https://www.dsn.kastel.kit.edu/bitcoin/snapshots/"
# One KIT snapshot per year, the first one on or after 1 October,
KIT_ANNUAL = [
    "20151001_123237", "20161001_121139", "20171002_124545", "20181001_123311",
    "20191001_121419", "20201001_124209", "20211001_122525", "20221001_124641",
    "20231001_120427", "20241001_123228", "20251001_122751", "20261001_121453",
]
# and the last seven daily ones before our crawl, to see how much a single day varies.
KIT_RECENT = [
    "20260927_*", "20260928_*", "20260929_*", "20260930_*",
    "20261002_*", "20261003_121755",
]

SOURCES = {
    # Routing and registry data
    "caida/routeviews-rv2-20260930-1200.pfx2as.gz":
        "https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/2026/09/routeviews-rv2-20260930-1200.pfx2as.gz",
    "caida/routeviews-rv6-20260930-1200.pfx2as.gz":
        "https://publicdata.caida.org/datasets/routing/routeviews6-prefix2as/2026/09/routeviews-rv6-20260930-1200.pfx2as.gz",
    "caida/20260901.as-org2info.jsonl.gz":
        "https://publicdata.caida.org/datasets/as-organizations/20260901.as-org2info.jsonl.gz",
    "caida/all-ip-ranges-20260905.csv":
        "https://publicdata.caida.org/datasets/cloud-prefixes/2026/09/all-ip-ranges-20260905.csv",
    "rir/nro-delegated-stats":
        "https://ftp.ripe.net/pub/stats/ripencc/nro-stats/latest/nro-delegated-stats",
    "peeringdb/net.json":
        "https://www.peeringdb.com/api/net?fields=asn,name,info_type,info_types,org_id",
    "apnic/aspop.json":
        "https://stats.labs.apnic.net/cgi-bin/aspop?c=&f=j",
    "dbip/dbip-country-lite-2026-10.csv.gz":
        "https://download.db-ip.com/free/dbip-country-lite-2026-10.csv.gz",
    # IP ranges published by the cloud providers themselves
    "cloud/aws-ip-ranges.json": "https://ip-ranges.amazonaws.com/ip-ranges.json",
    "cloud/gcp-cloud.json": "https://www.gstatic.com/ipranges/cloud.json",
    "cloud/oracle-public_ip_ranges.json": "https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json",
    "cloud/digitalocean-geo.csv": "https://digitalocean.com/geo/google.csv",
    "cloud/linode-geofeed.csv": "https://geoip.linode.com/",
    # Node count estimates
    "luke_uainfo.json": "https://luke.dashjr.org/programs/bitcoin/files/charts/data/uainfo.json",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_rows() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    with open(MANIFEST, newline="") as f:
        return {r["file"]: r for r in csv.DictReader(f)}


def write_manifest(rows: dict[str, dict]) -> None:
    with open(MANIFEST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "url", "retrieved_utc", "bytes", "sha256"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def fetch(rel: str, url: str, rows: dict[str, dict]) -> None:
    dest = RAW / rel
    if dest.exists() and dest.stat().st_size > 0:
        if rel not in rows:  # file obtained earlier (e.g. manually) -> still record it
            rows[rel] = dict(file=rel, url=url, retrieved_utc=dt.datetime.fromtimestamp(
                dest.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
                bytes=dest.stat().st_size, sha256=sha256(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"GET {url}", file=sys.stderr)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=300)
            r.raise_for_status()
            break
        except requests.RequestException as e:  # pragma: no cover - network
            print(f"  attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(5)
    else:
        print(f"  GIVING UP on {url}", file=sys.stderr)
        return
    dest.write_bytes(r.content)
    rows[rel] = dict(file=rel, url=url,
                     retrieved_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     bytes=dest.stat().st_size, sha256=sha256(dest))


def kit_files() -> dict[str, str]:
    listing = requests.get(KIT_BASE + "?curl", headers=UA, timeout=120).text.split()
    names = [u.rsplit("/", 1)[1] for u in listing]
    out = {}
    for pat in KIT_ANNUAL + KIT_RECENT:
        if pat.endswith("*"):
            match = sorted(n for n in names if n.startswith(pat[:-1]))
            if not match:
                continue
            name = match[0]
        else:
            name = pat + "_dossier.json"
        out[f"kit/{name}"] = KIT_BASE + name
    return out


def main() -> None:
    rows = manifest_rows()
    srcs = dict(SOURCES)
    srcs.update(kit_files())
    # We downloaded the Bitnodes snapshot once (the API allows 10 requests per day),
    # so it is listed here but never fetched again.
    srcs["bitnodes_snapshot_1791105141.json"] = "https://bitnodes.io/api/v1/snapshots/latest/"
    for rel, url in srcs.items():
        fetch(rel, url, rows)
        write_manifest(rows)
    print(f"{len(rows)} files recorded in {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
