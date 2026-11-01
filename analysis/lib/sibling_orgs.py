"""Merges companies that show up under several CAIDA AS2Org records.

Amazon, for example, appears as both "Amazon.com, Inc." and "Amazon Technologies
Inc.". If a CAIDA organisation name matches one of the patterns below, it is
counted under that group's name. Everything else keeps its CAIDA name.

The list was written before the concentration analysis
(see 00_methodology_preregistration.md). Merging can only make a provider look
bigger, never smaller, so the results are reported with and without it.
"""
import re

SIBLING_GROUPS: list[tuple[str, str]] = [
    ("Amazon", r"^amazon"),
    ("Google", r"^google"),
    ("Microsoft", r"^microsoft"),
    ("Oracle", r"^oracle"),
    ("Alibaba", r"alibaba|aliyun"),
    ("Tencent", r"tencent"),
    ("Huawei Cloud", r"huawei cloud|huawei clouds"),
    ("Hetzner", r"hetzner"),
    ("OVHcloud", r"^ovh"),
    ("Contabo", r"contabo"),
    ("DigitalOcean", r"digitalocean|digital ocean"),
    ("Akamai/Linode", r"^akamai|^linode"),
    ("Hostinger", r"hostinger"),
    ("IONOS", r"ionos|1&1 internet"),
    ("Leaseweb", r"leaseweb"),
    ("Vultr/Constant", r"^vultr|^choopa|^the constant company"),
    ("Scaleway/Iliad", r"^scaleway|^online s\.?a\.?s|^iliad|^free sas|^free mobile"),
    ("Comcast", r"^comcast"),
    ("Charter", r"^charter communications"),
    ("AT&T", r"^at&t|^at & t"),
    ("Verizon", r"^verizon|^mci communications|^cellco"),
    ("Deutsche Telekom", r"^deutsche telekom"),
    ("Vodafone", r"^vodafone"),
    ("Orange", r"^orange|^france telecom"),
    ("Telefonica", r"^telef[oó]nica"),
    ("NTT", r"^ntt "),
    ("Cox", r"^cox communications"),
    ("Rogers", r"^rogers communications"),
    ("Bell Canada", r"^bell canada"),
    ("Liberty Global", r"^liberty global|^virgin media|^ziggo|^telenet|^upc "),
]

_COMPILED = [(label, re.compile(rx, re.I)) for label, rx in SIBLING_GROUPS]


def merge_org(name: str | None) -> str | None:
    if not name:
        return name
    for label, rx in _COMPILED:
        if rx.search(name):
            return label
    return name
