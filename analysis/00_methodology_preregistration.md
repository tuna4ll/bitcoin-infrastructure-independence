# Measurement protocol (fixed before the quantitative analysis)

Written 2026-10-04 ~09:35 UTC, while the independent crawl (`02_crawl.py`) was
running and before any concentration metric was computed.

**Disclosure.** Before this protocol was written, the format of the KIT DSN dossier was
inspected. That check printed the ten most frequent ASNs in a subset of one
snapshot (AS396982/Google and AS16509/Amazon ranked first and second). The
protocol below was not changed in response to that output. The curated
hosting-ASN list (H2) uses widely known hosting providers and does not depend on it.

## 1. Datasets and roles

| ID | Dataset | Role |
|----|---------|------|
| D1 | Own BFS crawl from one vantage point in Türkiye (2026-10-04) | Primary IPv4/IPv6 reachable set; advertised overlay addresses |
| D2 | Bitnodes/btcnodes snapshot 1791105141 (2026-10-04 09:12:21 UTC) | Independent crawler; IPv4/IPv6 + verified Tor/I2P/CJDNS counts |
| D3 | KIT DSN dossiers (2026-09-27 to 2026-10-03; annual 1 Oct 2015-2026) | Independent academic monitor; KIT's own ASN attribution; time series |
| D4 | Luke Dashjr `uainfo.json` (2026-10-04) | Estimate of listening vs. non-listening nodes (methodology not published) |

No single dataset is treated as ground truth. Every headline number is reported
for each dataset where that dataset allows it.

## 2. Unit of analysis

* Primary unit: **unique IP address** among endpoints that completed a version
  handshake (D1, D2). If one IP runs several ports, it is counted once.
* Sensitivity checks: (a) IP:port endpoints; (b) aggregation to IPv4 /24 and IPv6 /48
  as a crude proxy for "same operator".
* Overlay addresses (Tor v3, I2P, CJDNS) are reported as a separate, **unattributable**
  category. They are never assigned to an ASN, provider or country.

## 3. Attribution

* **ASN:** longest-prefix match against CAIDA RouteViews prefix2as (IPv4 and IPv6,
  2026-09-30 12:00). Multi-origin prefixes use the first listed origin and are flagged.
* **Organisation/provider:** CAIDA AS2Org (2026-09-01): ASN → org_id → org name/country.
  Sibling organisations of the same corporate group (e.g. Amazon.com Inc. and Amazon
  Technologies Inc.) are merged only through an explicit, published table
  (`analysis/lib/sibling_orgs.py`), and only for groups named there. Results are
  reported both unmerged and merged.
* **Country:** (a) DB-IP IP-to-Country Lite (2026-10, CC BY 4.0) geolocation;
  (b) RIR registration country from NRO extended delegated stats. Both are reported,
  and their disagreement rate is reported as a validity indicator.
* **Infrastructure class** (a tiered rule, so that results come as bounds, not a point estimate):
  * **H1 cloud-verified:** the IP lies inside a provider-published range (AWS, GCP, Oracle,
    DigitalOcean, Linode/Akamai; plus CAIDA cloud-prefixes for Azure, IBM, Cloudflare, Fastly).
  * **H2 hosting-likely:** not H1, and the origin AS meets at least one of these conditions:
    (i) PeeringDB `info_types` contains `Content`; (ii) the AS is on a curated list of
    hosting/VPS providers written before analysis; (iii) the AS or org name matches
    `hosting|cloud|server|data ?cent|datacenter|vps|colo|dedicated`.
  * **R residential/access-likely:** not H1 or H2, and either APNIC's estimate for the AS
    is ≥ 10,000 end users or PeeringDB `info_types` contains `Cable/DSL/ISP`.
  * **U unclassified:** everything else.
  * Reported bounds: hosted share ∈ [H1, H1+H2+U]; central estimate H1+H2.

## 4. Metrics (computed over groups g with share s_g of attributable nodes)

* Counts and percentage shares; top-1, top-5 and top-10 cumulative share.
* HHI = Σ s_g² × 10,000 (0-10,000). Effective number of groups = 10,000 / HHI.
* Gini coefficient over group sizes. This is reported only alongside the number of
  groups, because it depends on the long tail of size-1 groups.
* Minimum number of groups whose removal takes away ≥ 33 % / ≥ 50 % of attributable nodes
  (a "Nakamoto-style" coefficient). **It is not a consensus-control measure.**
* Reference points (not normative): the 2023 U.S. DOJ/FTC Merger Guidelines treat
  HHI > 1,800 as "highly concentrated".
* Uncertainty: there is no random sample, so sampling CIs would mislead. Robustness
  is assessed by (i) agreement across D1/D2/D3, (ii) day-to-day variation over 7 KIT
  dossiers, and (iii) the classification bounds above.

## 5. Failure scenarios

Removal of: the top ASN; the top provider (merged org); the top country; the top-5
providers simultaneously; and all H1+H2 infrastructure. For each, the outputs are:

1. observable nodes lost under three denominators: IP-reachable; all reachable incl. overlay;
   reachable + D4 non-listening estimate (under the two extreme assumptions that
   non-listening nodes are unaffected / affected in proportion);
2. a **synthetic topology model** built from Bitcoin Core's outbound rules (8 full-relay +
   2 block-relay-only outbound connections to reachable peers, at most one per IPv4 /16 or
   IPv6 /32 netgroup, plus the attempt to keep ≥ 1 peer per reachable network). The model
   outputs are: largest connected component; share of nodes left with zero outbound peers;
   mean hop distance (a propagation-delay proxy). It is a model, **not a measurement** of the
   real topology, which is not publicly observable.
3. a modelled eclipse-exposure indicator: the share of nodes whose outbound peers are all
   inside a single provider, under /16 bucketing vs. AS-based bucketing (`-asmap`).

Interpretation rule: node loss is never translated into "control" over consensus.
Node availability, connectivity, transaction propagation, block propagation, eclipse
resistance, validation (consensus participation), hash power and ownership are treated
as distinct dimensions.

## 6. Time series

KIT annual dossiers (1 Oct 2015-2026), using KIT's own ASN attribution at each date:
ASN HHI, top-10 share, share of nodes in hosting-classified ASNs (2026 classification
applied backwards; this is flagged as an anachronism risk), and AS-registration-country HHI.

## 7. Composite index decision rule

A single "Infrastructure Independence Index" is produced only if the weights can be
derived from something other than researcher judgement (for example, a validated model
linking each dimension to a measurable resilience outcome). Otherwise, each dimension
is reported separately.
