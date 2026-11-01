#!/usr/bin/env python3
"""Hides node addresses and checks that nothing publishable contains one.

data/processed/ and some files in data/raw/ contain IP, onion and I2P addresses of
individual nodes. Many of them are home connections, which makes them personal
data in most places, so they must not end up in the repository or the public
release. The release zip itself is built by GitHub Actions
(.github/workflows/release.yml) from the files tracked in git, so this script
checks exactly those files.

Steps:
1. Replace addresses with pseudonyms using HMAC-SHA256 and a secret key, cut to
   64 bits. The key is created once in data/.anon_key and never published. A plain
   hash wouldn't be enough, because someone could simply hash all ~4 billion IPv4
   addresses and match them. The same input always gives the same pseudonym, so
   overlaps between datasets and grouping by subnet or netgroup still work.
     ip       -> "n:<hex>"   IP or overlay address
     subnet   -> "s:<hex>"   IPv4 /24, IPv6 /48
     netgroup -> "g:<hex>"   IPv4 /16, IPv6 /32
   ASN, organisation, provider, country, class, client, height and so on are kept,
   so steps 05 to 08 can be re-run on the public data with
       BII_PROCESSED=data/public/processed python analysis/05_concentration.py
2. Save the pseudonymised tables in data/public/processed/, together with
   raw_derived.json, which holds the few numbers that otherwise need the raw crawl files.
3. List the files that would be published: the files git tracks or would track
   (`git ls-files --cached --others --exclude-standard`), or, outside a git
   checkout, everything not matched by EXCLUDE (which mirrors .gitignore).
4. Search every text file in that list for any node address we know of (all
   probed IPs, all D1/D1b/D2 IPs, all overlay addresses). If even one shows up,
   the script stops with an error. Run this before every commit that touches data.
"""
from __future__ import annotations

import fnmatch
import glob
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC, PUB = ROOT / "data" / "processed", ROOT / "data" / "public" / "processed"
KEYFILE = ROOT / "data" / ".anon_key"

EXCLUDE = [
    ".venv/*", "release/*", "data/.anon_key", "data/processed/*",
    "data/raw/crawl/*.jsonl", "data/raw/crawl/*_overlay.json",
    "data/raw/crawl_aws*/*.jsonl", "data/raw/crawl_aws*/*_overlay.json",
    "data/raw/*/bitnodes_snapshot_*.json",
    "data/raw/bitnodes_snapshot_*.json",
    "paper/*.aux", "paper/*.log", "paper/*.blg", "paper/*.bbl", "paper/*.out",
    "paper/*.fls", "paper/*.fdb_latexmk", "paper/*.synctex.gz",
    "*/__pycache__/*", "*.pyc", ".git/*",
]


def key() -> bytes:
    if not KEYFILE.exists():
        KEYFILE.write_text(secrets.token_hex(32))
        os.chmod(KEYFILE, 0o600)
    return bytes.fromhex(KEYFILE.read_text().strip())


def pseudo(k: bytes, prefix: str):
    cache: dict[str, str] = {}

    def f(v):
        if pd.isna(v):
            return v
        v = str(v)
        if v not in cache:
            cache[v] = prefix + hmac.new(k, v.encode(), hashlib.sha256).hexdigest()[:16]
        return cache[v]
    return f


def pseudonymise() -> None:
    k = key()
    PUB.mkdir(parents=True, exist_ok=True)
    pid, psub, png = pseudo(k, "n:"), pseudo(k, "s:"), pseudo(k, "g:")
    for path in sorted(PROC.glob("*.csv")):
        df = pd.read_csv(path, low_memory=False)
        if "ip" in df:
            df["ip"] = df["ip"].map(pid)
        if "subnet" in df:
            df["subnet"] = df["subnet"].map(psub)
        if "netgroup" in df:
            df["netgroup"] = df["netgroup"].map(png)
        df.to_csv(PUB / path.name, index=False)
    # the few numbers in the paper that come straight from the raw crawl files
    d2 = pd.read_csv(PROC / "d2_bitnodes_nodes.csv", low_memory=False)
    fleet = (d2.services == 3077) & (d2.user_agent == "/Satoshi:27.0.0/")
    crawl = sorted(glob.glob(str(ROOT / "data" / "raw" / "crawl" / "crawl_*[0-9].jsonl")))[-1]
    hosts = {json.loads(l)["host"] for l in open(crawl)}
    aws = sorted(glob.glob(str(ROOT / "data" / "raw" / "crawl_aws" / "crawl_*[0-9].jsonl")))[-1]
    recs = [json.loads(l) for l in open(aws)]
    aws_hosts = {r["host"] for r in recs}
    aws_ok = {r["host"] for r in recs if r["status"] == "ok"}
    (PUB / "raw_derived.json").write_text(json.dumps(
        {"fleet_seen_by_d1": int(d2[fleet].ip.isin(hosts).sum()),
         "fleet_seen_by_d1b": int(d2[fleet].ip.isin(aws_hosts).sum()),
         "fleet_ok_in_d1b": int(d2[fleet].ip.isin(aws_ok).sum())}, indent=2))
    print(f"pseudonymised {len(list(PUB.glob('*.csv')))} tables -> {PUB.relative_to(ROOT)}")


def excluded(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in EXCLUDE)


def known_addresses() -> set[str]:
    addrs: set[str] = set()
    for f in glob.glob(str(ROOT / "data" / "raw" / "crawl*" / "*.jsonl")):
        for l in open(f):
            addrs.add(json.loads(l)["host"])
    for f in ["d1_crawl_nodes.csv", "d1b_crawl_nodes.csv", "d2_bitnodes_nodes.csv", "d2_bitnodes_overlay.csv",
              "d1b_20261006_crawl_nodes.csv", "d2_20261006_bitnodes_nodes.csv", "d2_20261006_bitnodes_overlay.csv"]:
        addrs |= set(pd.read_csv(PROC / f, usecols=["ip"], low_memory=False)["ip"].astype(str))
    for f in glob.glob(str(ROOT / "data" / "raw" / "crawl*" / "*_overlay.json")):
        for kk in json.load(open(f)):
            addrs.add(kk.split(":", 2)[1])  # "<net>:<host>:<port>"
    return addrs


TOKEN = re.compile(r"[0-9A-Za-z.:\[\]_-]{7,}")


def normalise(tok: str) -> list[str]:
    tok = tok.strip("[]")
    out = [tok]
    for cand in (tok, tok.rsplit(":", 1)[0].strip("[]")):
        try:
            out.append(str(ipaddress.ip_address(cand)))
        except ValueError:
            pass
    return out


def publishable_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode()
        return sorted(f for f in out.split("\0") if f and (ROOT / f).is_file())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                      if p.is_file() and not excluded(p.relative_to(ROOT).as_posix()))


def check() -> None:
    files = publishable_files()
    forbidden = [f for f in files if excluded(f) and not f.startswith("paper/")]
    if forbidden:
        print("files that must never be published are not ignored by git:", *forbidden[:10], sep="\n  ")
        sys.exit(1)
    known = known_addresses()
    # Public reference files (BGP tables, cloud ranges, RIR and DB-IP blocks) list prefix
    # start addresses, and now and then one of those equals a node IP by chance.
    # We count those matches but don't treat them as leaks.
    # The Bitcoin Core source also has made-up example addresses in its comments.
    reference = ("data/raw/caida/", "data/raw/cloud/", "data/raw/rir/", "data/raw/dbip/",
                 "data/raw/bitcoin-core/")
    leaks, ref_hits, scanned = [], 0, 0
    for rel in files:
        if rel.endswith((".pdf", ".png", ".zip")):
            continue
        raw = (ROOT / rel).read_bytes()
        if rel.endswith(".gz"):
            import gzip
            raw = gzip.decompress(raw)
        data = raw.decode("utf-8", "ignore")
        scanned += 1
        hits = {n for tok in TOKEN.findall(data) for n in normalise(tok) if n in known}
        if hits:
            if rel.startswith(reference):
                ref_hits += len(hits)
            else:
                leaks.append((rel, sorted(hits)[:3], len(hits)))
    print(f"leak check: scanned {scanned} of {len(files)} publishable files against "
          f"{len(known):,} known node addresses")
    print(f"  coincidental matches inside public prefix/reference tables: {ref_hits}")
    if leaks:
        for rel, ex, n in leaks:
            print(f"  LEAK {rel}: {n} addresses, e.g. {ex}")
        sys.exit(1)
    print("  no node address found outside reference tables: OK")


if __name__ == "__main__":
    os.chdir(ROOT)
    pseudonymise()
    check()
