"""Looks up the ASN, organisation, country and infrastructure class of an IP.

Everything runs offline, using the files listed in data/raw/MANIFEST.csv.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import ipaddress
import json
import re
from functools import lru_cache
from pathlib import Path

from .sibling_orgs import merge_org

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

PFX2AS_V4 = RAW / "caida" / "routeviews-rv2-20260930-1200.pfx2as.gz"
PFX2AS_V6 = RAW / "caida" / "routeviews-rv6-20260930-1200.pfx2as.gz"
AS2ORG = RAW / "caida" / "20260901.as-org2info.jsonl.gz"
DBIP = RAW / "dbip" / "dbip-country-lite-2026-10.csv.gz"
NRO = RAW / "rir" / "nro-delegated-stats"
PEERINGDB = RAW / "peeringdb" / "net.json"
APNIC = RAW / "apnic" / "aspop.json"

# Hand-picked hosting, VPS and cloud ASNs (rule H2-ii), written down before the analysis.
# Only well-known companies whose main business is renting out servers are on it.
HOSTING_ASNS: dict[int, str] = {
    16509: "Amazon", 14618: "Amazon", 15169: "Google", 396982: "Google Cloud", 19527: "Google",
    8075: "Microsoft", 31898: "Oracle", 45102: "Alibaba", 37963: "Alibaba",
    132203: "Tencent", 45090: "Tencent", 55990: "Huawei Cloud", 136907: "Huawei Cloud",
    135377: "UCloud", 24940: "Hetzner", 213230: "Hetzner", 212317: "Hetzner",
    16276: "OVH", 51167: "Contabo", 40021: "Contabo", 141995: "Contabo",
    47583: "Hostinger", 197540: "netcup", 20473: "Vultr", 14061: "DigitalOcean",
    63949: "Akamai/Linode", 60781: "Leaseweb", 16265: "Leaseweb", 28753: "Leaseweb",
    59253: "Leaseweb", 12876: "Scaleway", 8560: "IONOS", 36352: "ColoCrossing",
    40676: "Psychz", 9009: "M247", 62240: "Clouvider", 51852: "Private Layer",
    29802: "Hivelocity", 23470: "ReliableSite", 53667: "FranTech/BuyVM",
    54290: "Hostwinds", 8100: "QuadraNet", 25820: "IT7", 3223: "Voxility",
    210644: "Aeza", 49981: "WorldStream", 50673: "Serverius", 18450: "WebNX",
    36351: "IBM SoftLayer", 22612: "Namecheap", 26496: "GoDaddy", 398101: "GoDaddy",
    30083: "GoDaddy", 32244: "Liquid Web",
}
HOSTING_NAME_RX = re.compile(r"hosting|cloud|server|data ?cent|datacenter|vps|colo|dedicated", re.I)
APNIC_EYEBALL_MIN_USERS = 10_000


# helpers
class PrefixTable:
    """Longest-prefix match: one dict per prefix length, keyed by network address."""

    def __init__(self, version: int):
        self.version = version
        self.maxlen = 32 if version == 4 else 128
        self.tables: dict[int, dict[int, object]] = {}

    def add(self, net: ipaddress._BaseNetwork, value) -> None:
        self.tables.setdefault(net.prefixlen, {}).setdefault(int(net.network_address), value)

    def lookup(self, ip: ipaddress._BaseAddress):
        x = int(ip)
        for plen in sorted(self.tables, reverse=True):
            key = (x >> (self.maxlen - plen)) << (self.maxlen - plen)
            v = self.tables[plen].get(key)
            if v is not None:
                return v, plen
        return None, None


class RangeTable:
    """Sorted [start, end] ranges that don't overlap, searched with bisect."""

    def __init__(self):
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.vals: list = []

    def finalize(self):
        order = sorted(range(len(self.starts)), key=self.starts.__getitem__)
        self.starts = [self.starts[i] for i in order]
        self.ends = [self.ends[i] for i in order]
        self.vals = [self.vals[i] for i in order]

    def lookup(self, x: int):
        i = bisect.bisect_right(self.starts, x) - 1
        if i >= 0 and x <= self.ends[i]:
            return self.vals[i]
        return None


# loaders
@lru_cache(None)
def pfx2as() -> dict[int, PrefixTable]:
    tabs = {4: PrefixTable(4), 6: PrefixTable(6)}
    for path, ver in ((PFX2AS_V4, 4), (PFX2AS_V6, 6)):
        with gzip.open(path, "rt") as f:
            for line in f:
                pfx, plen, origin = line.split()
                net = ipaddress.ip_network(f"{pfx}/{plen}", strict=False)
                first = re.split(r"[_,]", origin)[0]
                tabs[ver].add(net, (int(first), bool(re.search(r"[_,]", origin))))
    return tabs


@lru_cache(None)
def as2org() -> dict[int, dict]:
    orgs, asns = {}, {}
    with gzip.open(AS2ORG, "rt") as f:
        for line in f:
            r = json.loads(line)
            if r.get("type") == "Organization":
                orgs[r["organizationId"]] = r
            elif r.get("type") == "ASN":
                asns[int(r["asn"])] = r
    out = {}
    for asn, r in asns.items():
        o = orgs.get(r.get("organizationId"), {})
        out[asn] = {"as_name": r.get("name", ""), "org_id": r.get("organizationId"),
                    "org_name": o.get("name") or r.get("name", ""), "org_country": o.get("country")}
    return out


@lru_cache(None)
def dbip() -> dict[int, RangeTable]:
    tabs = {4: RangeTable(), 6: RangeTable()}
    with gzip.open(DBIP, "rt") as f:
        for start, end, cc in csv.reader(f):
            a, b = ipaddress.ip_address(start), ipaddress.ip_address(end)
            t = tabs[a.version]
            t.starts.append(int(a)); t.ends.append(int(b)); t.vals.append(cc)
    for t in tabs.values():
        t.finalize()
    return tabs


@lru_cache(None)
def nro() -> dict[int, RangeTable]:
    tabs = {4: RangeTable(), 6: RangeTable()}
    with open(NRO) as f:
        for line in f:
            p = line.rstrip("\n").split("|")
            if len(p) < 7 or p[2] not in ("ipv4", "ipv6") or p[1] in ("*", "") or p[3] == "*":
                continue
            if p[6] not in ("allocated", "assigned"):
                continue
            start = ipaddress.ip_address(p[3])
            if p[2] == "ipv4":
                end = int(start) + int(p[4]) - 1
            else:
                end = int(start) + (1 << (128 - int(p[4]))) - 1
            t = tabs[start.version]
            t.starts.append(int(start)); t.ends.append(end); t.vals.append((p[1], p[0]))
    for t in tabs.values():
        t.finalize()
    return tabs


@lru_cache(None)
def cloud_ranges() -> dict[int, PrefixTable]:
    tabs = {4: PrefixTable(4), 6: PrefixTable(6)}

    def add(cidr: str, provider: str):
        try:
            net = ipaddress.ip_network(cidr.strip(), strict=False)
        except ValueError:
            return
        tabs[net.version].add(net, provider)

    aws = json.load(open(RAW / "cloud" / "aws-ip-ranges.json"))
    for p in aws["prefixes"]:
        add(p["ip_prefix"], "Amazon")
    for p in aws["ipv6_prefixes"]:
        add(p["ipv6_prefix"], "Amazon")
    for p in json.load(open(RAW / "cloud" / "gcp-cloud.json"))["prefixes"]:
        add(p.get("ipv4Prefix") or p.get("ipv6Prefix"), "Google")
    for reg in json.load(open(RAW / "cloud" / "oracle-public_ip_ranges.json"))["regions"]:
        for c in reg["cidrs"]:
            add(c["cidr"], "Oracle")
    with open(RAW / "cloud" / "digitalocean-geo.csv") as f:
        for row in csv.reader(f):
            if row:
                add(row[0], "DigitalOcean")
    with open(RAW / "cloud" / "linode-geofeed.csv") as f:
        for row in csv.reader(f):
            if row and not row[0].startswith("#"):
                add(row[0], "Akamai/Linode")
    names = {"Azure": "Microsoft", "IBM": "IBM", "CloudFlare": "Cloudflare", "Fastly": "Fastly"}
    with open(RAW / "caida" / "all-ip-ranges-20260905.csv") as f:
        for row in csv.DictReader(f):
            if row["provider"] in names:
                add(row["cidr_block"], names[row["provider"]])
    return tabs


@lru_cache(None)
def peeringdb_types() -> dict[int, set[str]]:
    out = {}
    for n in json.load(open(PEERINGDB))["data"]:
        types = set(n.get("info_types") or [])
        if n.get("info_type"):
            types.add(n["info_type"])
        out[int(n["asn"])] = types
    return out


@lru_cache(None)
def apnic_users() -> dict[int, int]:
    d = json.load(open(APNIC))
    out: dict[int, int] = {}
    for r in d["Data"]:
        out[int(r["AS"])] = out.get(int(r["AS"]), 0) + int(r["Users"])
    return out


# public API
def classify_asn(asn: int | None, as_name: str, org_name: str) -> tuple[str, str]:
    """Returns (class, reason) using the ASN-level rules H2, R and U."""
    if asn is None:
        return "U", "no-asn"
    pdb = peeringdb_types().get(asn, set())
    if "Content" in pdb:
        return "H2", "peeringdb-content"
    if asn in HOSTING_ASNS:
        return "H2", "curated-list"
    if HOSTING_NAME_RX.search(as_name or "") or HOSTING_NAME_RX.search(org_name or ""):
        return "H2", "name-regex"
    if apnic_users().get(asn, 0) >= APNIC_EYEBALL_MIN_USERS:
        return "R", "apnic-users"
    if "Cable/DSL/ISP" in pdb:
        return "R", "peeringdb-isp"
    return "U", "unmatched"


def attribute(ip_str: str) -> dict:
    ip = ipaddress.ip_address(ip_str)
    v = ip.version
    (asn_moas, plen) = pfx2as()[v].lookup(ip)
    asn, moas = (asn_moas if asn_moas else (None, False))
    org = as2org().get(asn, {}) if asn else {}
    cloud, _ = cloud_ranges()[v].lookup(ip)
    geo_cc = dbip()[v].lookup(int(ip))
    reg = nro()[v].lookup(int(ip))
    cls, reason = ("H1", f"cloud-range:{cloud}") if cloud else classify_asn(
        asn, org.get("as_name", ""), org.get("org_name", ""))
    org_name = org.get("org_name") or (f"AS{asn}" if asn else None)
    if v == 4:
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        netgroup = str(ipaddress.ip_network(f"{ip}/16", strict=False))
    else:
        subnet = str(ipaddress.ip_network(f"{ip}/48", strict=False))
        netgroup = str(ipaddress.ip_network(f"{ip}/32", strict=False))
    return {
        "ip": ip_str, "ipver": v, "asn": asn, "moas": moas, "bgp_prefixlen": plen,
        "as_name": org.get("as_name"), "org_id": org.get("org_id"), "org": org_name,
        "provider": merge_org(org_name) if org_name else None,
        "org_country": org.get("org_country"),
        "geo_cc": geo_cc, "rir_cc": reg[0] if reg else None, "rir": reg[1] if reg else None,
        "cloud_range": cloud, "infra_class": cls, "class_reason": reason,
        "subnet": subnet, "netgroup": netgroup,
    }


def asn_info(asn: int) -> dict:
    org = as2org().get(asn, {})
    org_name = org.get("org_name") or f"AS{asn}"
    cls, reason = classify_asn(asn, org.get("as_name", ""), org.get("org_name", ""))
    return {"asn": asn, "as_name": org.get("as_name"), "org": org_name,
            "provider": merge_org(org_name), "infra_class": cls, "class_reason": reason}
