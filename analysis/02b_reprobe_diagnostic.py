#!/usr/bin/env python3
"""Checks whether the home crawl missed IPv4 nodes because of our own network.

The home crawl (D1) found far fewer IPv4 nodes than Bitnodes (D2) and KIT (D3),
while its IPv6 numbers looked normal. Our guess was that the home router's NAT
table filled up at 300 parallel connections. To test that, we take every IPv4
address that Bitnodes lists as reachable but that timed out in D1, and try it
again with only 30 parallel connections. If most of them answer now, the gap in
D1 comes from our setup and not from the network.

The results are kept separate and are not merged into D1.
"""
import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
crawl = importlib.import_module("02_crawl")
CONCURRENCY = 30


async def main() -> None:
    raw = ROOT / "data" / "raw" / "crawl"
    path = sorted(raw.glob("crawl_*[0-9].jsonl"))[-1]
    r = pd.DataFrame([json.loads(l) for l in open(path)])
    ok = set(zip(r[r.status == "ok"].host, r[r.status == "ok"].port))
    last = r.sort_values("pass").drop_duplicates(["host", "port"], keep="last").set_index(["host", "port"])["status"]
    d2 = pd.read_csv(ROOT / "data" / "processed" / "d2_bitnodes_nodes.csv", low_memory=False)
    targets = [(h, int(p)) for h, p, v in zip(d2.ip, d2.port, d2.ipver)
               if v == 4 and (h, p) not in ok and last.get((h, p)) == "timeout"]
    print(f"re-probing {len(targets)} endpoints at concurrency {CONCURRENCY}", file=sys.stderr)
    sem = asyncio.Semaphore(CONCURRENCY)
    out = []

    async def one(h, p):
        async with sem:
            rec, _ = await crawl.probe(h, p)
            out.append(rec)

    t0 = time.time()
    await asyncio.gather(*(one(h, p) for h, p in targets))
    res = pd.DataFrame(out)
    res.to_json(raw / f"reprobe_{int(t0)}.jsonl", orient="records", lines=True)
    summary = {"targets": len(targets), "concurrency": CONCURRENCY, "start_utc": int(t0),
               "duration_s": round(time.time() - t0), "status": res["status"].value_counts().to_dict()}
    (raw / f"reprobe_{int(t0)}_meta.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    os.chdir(ROOT)
    asyncio.run(main())
