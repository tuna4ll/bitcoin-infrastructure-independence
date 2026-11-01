# Bitcoin infrastructure independence

Tuna Kılıç, <tuna@tunakilic.com>, [tunakilic.com](https://tunakilic.com)

This project looks at where reachable Bitcoin nodes actually run. Are they spread
across many hosting companies, networks and countries, or packed into a few? And if
they are packed into a few, does that matter for how independent and resilient
Bitcoin is? The main measurements were taken on 3 and 4 October 2026, and two of them were
repeated on 6 October.

The paper source is `paper/paper.tex`; the PDF is built by CI and attached to each
[GitHub release](../../releases), or locally with `cd paper && latexmk -pdf paper.tex`. None of the numbers in
the text are typed by hand. They come from `analysis/08_paper_numbers.py`, which
writes them to `paper/numbers.tex`.

## What's where

```
paper/       the paper, references and the generated numbers
data/raw/    everything we downloaded or collected, plus MANIFEST.csv with URL, time and SHA-256 for each file
data/public/ pseudonymised node tables that are safe to share
analysis/    the scripts, numbered in the order they run, and a small lib/ folder
figures/     all figures as PDF and PNG, each with its data source printed under it
tables/      CSV and LaTeX tables, plus a few JSON files with side results
```

`data/processed/` holds the same node tables with real IP addresses. It stays on this
machine and is not part of the public release.

## The scripts

`analysis/00_methodology_preregistration.md` is the measurement plan. It was written
on 4 October 2026, before any results were computed, and has not been changed since.
It was not deposited with an outside registry, so that timing rests on our word.

| Script | What it does |
|---|---|
| `01_fetch_data.py` | downloads the external data and logs every file in `MANIFEST.csv` |
| `02_crawl.py` | our own crawler. It only does the normal handshake and asks for addresses |
| `02b_reprobe_diagnostic.py` | re-tests IPv4 nodes the home crawl missed, to check whether our router was the problem |
| `03_verify_literature.py` | checks the cited papers against Crossref |
| `04_build_datasets.py` | removes duplicates and looks up ASN, company, country and hosting type for every node |
| `05_concentration.py` | concentration numbers (top-k shares, HHI, Gini, N50) and most figures |
| `06_failure_scenarios.py` | what happens if big providers or countries go offline, counted and modelled |
| `06b_capacity.py` | how much connection demand the remaining nodes can still serve |
| `07_timeseries.py` | how things changed from 2015 to 2026, using KIT's yearly snapshots |
| `08_paper_numbers.py` | writes all numbers for the paper |
| `10_two_days.py` | compares 4 and 6 October: concentration, which nodes came and went, the fleet and the forked chains |
| `09_anonymize_release.py` | hides node addresses and checks every file that would go into git for leaks |

To run everything from scratch:

```bash
python3 -m venv .venv
.venv/bin/pip install pandas numpy matplotlib requests scipy
.venv/bin/python analysis/01_fetch_data.py
.venv/bin/python analysis/02_crawl.py                 # about 3 hours, connects to Bitcoin nodes
.venv/bin/python analysis/02b_reprobe_diagnostic.py   # optional, a few minutes
.venv/bin/python analysis/04_build_datasets.py
.venv/bin/python analysis/05_concentration.py
.venv/bin/python analysis/06_failure_scenarios.py     # about 1 hour
.venv/bin/python analysis/06b_capacity.py
.venv/bin/python analysis/07_timeseries.py
.venv/bin/python analysis/10_two_days.py
.venv/bin/python analysis/08_paper_numbers.py
.venv/bin/python analysis/09_anonymize_release.py
cd paper && latexmk -pdf paper.tex
```

If you crawl again you will of course get a different day's network. Bitnodes also only
allows 10 API requests per day, so the files in `data/raw/` are the exact inputs behind
the paper. From step 04 onwards everything is deterministic, and the model uses fixed
random seeds.

## Data

We used four sources of node data and never relied on just one of them.

D1 is our own crawl from a home connection in Türkiye (4 October, 09:33 to 12:33 UTC).
It turned out the home router couldn't handle 300 parallel connections and the crawl
missed many IPv4 nodes. When we retried the missed ones slowly, 83 % of them answered,
so the gap came from our setup and not from the network.

D1b is the same crawler run again on an AWS machine with no NAT in between (14:06 to
17:03 UTC). That machine had no IPv6, so D1b combines its IPv4 nodes with the IPv6 nodes
from D1. It found 86 % of the IPv4 nodes Bitnodes lists, plus 581 that Bitnodes doesn't.

D2 is a Bitnodes snapshot (bitnodes.io now redirects to btcnodes.io), taken at 09:12 UTC.
It is our main dataset because it also checks Tor and I2P nodes.

D3 is the KIT DSN Bitcoin monitor (doi:10.5281/zenodo.14627525). We used its daily file
from 3 October and one file per year from 2015 to 2026. KIT doesn't publish IPs, only
the ASN it looked up for each peer.

On 6 October we ran the AWS crawl again (14:48 to 17:49 UTC, again IPv4 only) and took a
second Bitnodes snapshot at 14:25 UTC. These files are in `data/raw/crawl_aws_20261006/`.

D4 is Luke Dashjr's estimate of how many nodes don't accept incoming connections. It's
the only estimate of that kind we found, but how it's made isn't published.

To find out who runs the network behind each IP we used CAIDA's prefix-to-AS and
AS-to-organisation data, the NRO registration files, DB-IP Lite for country, PeeringDB,
APNIC's user counts per AS, and the IP ranges that AWS, Google Cloud, Oracle,
DigitalOcean and Linode publish (plus CAIDA's copy for Azure and a few others). Facts
about how Bitcoin Core behaves were checked in its source code, both on master and in
release v31.0. All of this is listed in `data/raw/MANIFEST.csv`.

## What we found

In short, there is real concentration, but it doesn't give anyone control over Bitcoin.
The numbers below are for nodes that announce NODE_WITNESS, which are the only ones
current Bitcoin Core nodes will keep as outbound peers.

Only about a third of reachable nodes can be traced to a company or country at all. The
rest run over Tor, I2P or CJDNS.

Hetzner is the biggest host with about 10 to 11 % of nodes, and Bitnodes, KIT and our AWS
crawl all agree on that. The five biggest providers together have 29 to 32 %, and you
need 13 to 15 providers to cover half the nodes. Countries are more concentrated: the US
has about 31 % by geolocation and 39 % by registration, and three countries hold half
the nodes.

Somewhere between 12 and 49 % of nodes run in data centres. Our best estimate is 42 to
46 %. Roughly half run on home or business internet connections.

Looking back with KIT's data, concentration was highest around 2020 and has gone down
since. The share of nodes at hosting companies dropped from 61 % to 42 %.

Two things show why node counts need care. Bitnodes sees 849 identical, non-working nodes
at Linode, and if you counted them Linode would look like the biggest provider. And about
7 % of reachable nodes are following other chains, namely the Knots BLAKE2b hard fork and
the stalled BIP-110 branch. Most of them run at the same companies as everyone else (OVH, Hetzner, Comcast and
so on), just with different rules. So the number of nodes says nothing about who decides the rules.

In our model the network stays connected even if every hosting company went offline at
once. The weak spot is capacity. Only listening nodes accept connections, and with
Bitcoin Core's default of 125 connections they already can't take all the demand if D4's
estimate is right: about 14 % of it goes unserved. That rises to 21 % without Hetzner and
to 32 % without the top five providers or without the US. Grundmann et al. (ICBC 2022)
measured that almost all connection slots on reachable nodes are already taken, which
fits this picture. The other risk is a hosting company or network operator trying to take
over nodes' connections on purpose. In the model, Bitcoin Core's `-asmap` option makes
that much harder, but it is off by default.

Two days later almost nothing had changed at this level. Hetzner went from 11.0 % to 10.8 %
and the provider HHI moved by at most 6 points. Individual nodes do come and go though: of
the nodes our AWS crawl saw on 4 October, 93 % were back on 6 October, and hosted nodes
(97 %) stuck around more than home connections (90 %). The Linode fleet shrank from 849 to
617, and the BLAKE2b chain gained a few nodes (1,070 to 1,103).

The paper has the exact values, the ranges and the limitations.

## Privacy and the public release

The node tables contain IP, onion and I2P addresses, many of them home connections, so we
don't publish them. `09_anonymize_release.py` replaces every address, subnet and netgroup
with a pseudonym made with a secret key (HMAC-SHA256). The key lives in `data/.anon_key`
and should never be shared, because without it nobody can turn the pseudonyms back into
IPs. The public tables go to `data/public/processed/`. `.gitignore` keeps the raw crawl
files, the Bitnodes snapshots, `data/processed/` and the key out of the repository.
Finally the script searches every file git would publish for any of the roughly 360,000
node addresses we know about and stops if it finds one outside public reference files
like BGP tables. Run it before every commit that touches data.

Releases are built by GitHub Actions (`.github/workflows/release.yml`). Pushing a tag
such as `v1.0` compiles the paper and attaches the PDF and a zip of the repository to a
new GitHub release. The workflow also refuses to run if a private file was committed.

You can rerun steps 05 to 08 (including 06b and 10) on the public data by setting
`BII_PROCESSED=data/public/processed`. We checked this: all 746 numbers in the paper come
out exactly the same, and the model builds the same network. Steps 01 to 04 need the raw
addresses, so for those you'd have to run your own crawl.

## AI assistance

The code was written with help from Claude Opus 5.5 (Anthropic) through Claude Code. The
model also helped draft the paper and check the references against Crossref. I reviewed
the results and I'm responsible for the work.

## Ethics

The crawler only does what every Bitcoin node does when it meets a peer: the
version/verack handshake and a getaddr request. It says who it is
(`/bitcoin-infra-research:0.1/`) and never relays anything. Only the pseudonymised data
is published.
