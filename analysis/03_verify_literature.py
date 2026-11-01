#!/usr/bin/env python3
"""Checks that the papers we cite actually exist, using the Crossref API.

For each title we take Crossref's best match. A paper is only cited if title,
authors and year all match, and DOIs are copied from Crossref rather than
typed in. Works without a DOI (USENIX, NDSS, arXiv, reports) were checked by
hand against their official pages.
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "literature_crossref.json"
UA = {"User-Agent": "bitcoin-infrastructure-independence/0.1 (mailto:research@example.invalid)"}

CANDIDATES = [
    "Information propagation in the Bitcoin network",
    "Hijacking Bitcoin: Routing Attacks on Cryptocurrencies",
    "Decentralization in Bitcoin and Ethereum Networks",
    "Network Layer Aspects of Permissionless Blockchains",
    "Analyzing the Deployment of Bitcoin's P2P Network under an AS-level Perspective",
    "The Bitcoin P2P Network",
    "Deanonymisation of clients in Bitcoin P2P network",
    "Bitcoin over Tor isn't a Good Idea",
    "A Stealthier Partitioning Attack against Bitcoin Peer-to-Peer Network",
    "TxProbe: Discovering Bitcoin's Network Topology Using Orphan Transactions",
    "Timing Analysis for Inferring the Topology of the Bitcoin Peer-to-Peer Network",
    "Impossibility of Full Decentralization in Permissionless Blockchains",
    "Taxonomy of centralization in public blockchain systems: A systematic literature review",
    "ASdb: a system for classifying owners of autonomous systems",
    "Analyzing third party service dependencies in modern web services: have we learned from the mirai-dyn incident?",
    "Measuring Ethereum Network Peers",
    "Nodes in the Bitcoin Network: Comparative Measurement Study and Survey",
    "On Scaling Decentralized Blockchains",
    "Partitioning Attacks on Bitcoin: Colliding Space, Time, and Logic",
    "On the Peer Degree Distribution of the Bitcoin P2P Network",
    "Measuring Decentralization in Bitcoin and Ethereum using Multiple Metrics and Granularities",
    "Bitcoin's academic pedigree",
    "Discovering Bitcoin's Public Topology and Influential Nodes",
    "Eclipse Attacks on Bitcoin's Peer-to-Peer Network",
    "Majority is not enough: Bitcoin mining is vulnerable",
    "Variabilità e mutabilità",
    "The Herfindahl-Hirschman Index",
    "Characterizing Bitcoin's peer-to-peer network: An empirical study of unreachable nodes",
    "Towards Better Understanding of Bitcoin Unreachable Peers",
    "SoK: Research Perspectives and Challenges for Bitcoin and Cryptocurrencies",
    "Erlay: Efficient Transaction Relay for Bitcoin",
    "Cloud provider connectivity in the flat Internet",
    "A First Look at the Network Infrastructure of Ethereum Nodes",
    "Geolocation accuracy of IP databases",
    "IP geolocation databases: unreliable?",
    "Inferring the deployment of top domains over public clouds using DNS data",
    "Decentralization of Ethereum's validator set",
    "Blockchain decentralization measurement",
    "How decentralized is the Bitcoin network",
    "Characterizing the Bitcoin network infrastructure",
]


EXTRA = [
    "Bitcoin: A Peer-to-Peer Electronic Cash System",
    "Low-Resource Eclipse Attacks on Ethereum's Peer-to-Peer Network",
    "Mitigating eclipse attacks in peer-to-peer networks",
    "Revisiting Bitcoin's network: unreachable nodes",
    "Measuring the Concentration of Control in Contemporary Ethereum",
    "What Peer Announcements Tell Us About the Size of the Bitcoin P2P Network",
    "Estimating the Peer Degree of Reachable Peers in the Bitcoin P2P Network",
    "On the Estimation of the Number of Unreachable Peers in the Bitcoin P2P Network by Observation of Peer Announcements",
]


def query(title: str) -> dict:
    r = requests.get("https://api.crossref.org/works",
                     params={"query.bibliographic": title, "rows": 3,
                             "select": "DOI,title,author,issued,container-title,type,publisher"},
                     headers=UA, timeout=60)
    r.raise_for_status()
    items = r.json()["message"]["items"]
    res = []
    for it in items:
        res.append({
            "doi": it.get("DOI"),
            "title": (it.get("title") or [""])[0],
            "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in it.get("author", [])],
            "year": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "venue": (it.get("container-title") or [""])[0],
            "type": it.get("type"),
        })
    return {"query": title, "matches": res}


def safe_query(t: str) -> dict:
    err = ""
    for attempt in range(3):
        try:
            res = query(t)
            print(f"ok  {t[:60]}", file=sys.stderr, flush=True)
            return res
        except Exception as e:  # pragma: no cover - network
            time.sleep(2)
            err = str(e)
    print(f"ERR {t[:60]}: {err}", file=sys.stderr, flush=True)
    return {"query": t, "error": err}


def main():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:  # Crossref responses are slow (~30 s)
        out = list(ex.map(safe_query, CANDIDATES + EXTRA))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for o in out:
        m = (o.get("matches") or [{}])[0]
        print(f"Q: {o['query']}\n   -> {m.get('title')} | {m.get('year')} | {m.get('doi')} | "
              f"{', '.join(m.get('authors', [])[:4])} | {m.get('venue')}")


if __name__ == "__main__":
    sys.exit(main())
