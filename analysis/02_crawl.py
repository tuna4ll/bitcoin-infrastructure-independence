#!/usr/bin/env python3
"""A small breadth-first crawler for the reachable Bitcoin P2P network.

It works like the public crawlers (Bitnodes and others), but it is a separate
implementation that we run from our own vantage point.

How it works:
1. Resolve the mainnet DNS seeds listed in Bitcoin Core
   (src/kernel/chainparams.cpp, commit in data/raw/bitcoin-core/COMMIT).
2. Connect to each IPv4/IPv6 address and do the normal version/verack handshake.
   We announce services=0 and relay=0 and send an honest user agent. After the
   handshake we send sendaddrv2 and one getaddr, then collect the addr/addrv2
   replies for a few seconds. We never ask for or relay transactions or blocks.
3. Every IPv4/IPv6 address we learn whose timestamp is at most MAX_ADDR_AGE old
   goes into the queue and is probed once. Addresses that time out get one more
   try at the end.
4. Tor v3, I2P and CJDNS addresses are written down but not probed, since we
   don't run clients for those networks. So for them we only know that they
   were advertised, not that they are reachable.

Output files in data/raw/crawl/:
  crawl_<unix>.jsonl          one line per probed address
  crawl_<unix>_overlay.json   Tor/I2P/CJDNS addresses seen in gossip
  crawl_<unix>_meta.json      settings and a short summary
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import random
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "crawl"

MAGIC = bytes.fromhex("f9beb4d9")
PROTOCOL_VERSION = 70016
USER_AGENT = b"/bitcoin-infra-research:0.1/"
DNS_SEEDS = [  # Bitcoin Core master, src/kernel/chainparams.cpp (mainnet vSeeds)
    "seed.bitcoin.sipa.be", "dnsseed.bluematt.me", "seed.bitcoin.jonasschnelli.ch",
    "seed.btc.petertodd.net", "seed.bitcoin.sprovoost.nl", "dnsseed.emzy.de",
    "seed.bitcoin.wiz.biz", "seed.mainnet.achownodes.xyz",
]
CONCURRENCY = 300
CONNECT_TIMEOUT = 6.0
HANDSHAKE_TIMEOUT = 10.0
GETADDR_WINDOW = 12.0
MAX_ADDR_AGE = 7 * 24 * 3600  # seconds

NET_IDS = {1: "ipv4", 2: "ipv6", 3: "torv2", 4: "onion", 5: "i2p", 6: "cjdns"}


# wire format
def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def msg(command: str, payload: bytes = b"") -> bytes:
    return (MAGIC + command.encode().ljust(12, b"\0") + struct.pack("<I", len(payload))
            + sha256d(payload)[:4] + payload)


def varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def read_varint(b: bytes, i: int) -> tuple[int, int]:
    p = b[i]
    if p < 0xFD:
        return p, i + 1
    if p == 0xFD:
        return struct.unpack_from("<H", b, i + 1)[0], i + 3
    if p == 0xFE:
        return struct.unpack_from("<I", b, i + 1)[0], i + 5
    return struct.unpack_from("<Q", b, i + 1)[0], i + 9


def ip16(host: str) -> bytes:
    ip = ipaddress.ip_address(host)
    if ip.version == 4:
        return b"\0" * 10 + b"\xff\xff" + ip.packed
    return ip.packed


def version_payload(host: str, port: int) -> bytes:
    addr_recv = struct.pack("<Q", 0) + ip16(host) + struct.pack(">H", port)
    addr_from = struct.pack("<Q", 0) + b"\0" * 16 + struct.pack(">H", 0)
    return (struct.pack("<iQq", PROTOCOL_VERSION, 0, int(time.time())) + addr_recv + addr_from
            + struct.pack("<Q", random.getrandbits(64)) + varint(len(USER_AGENT)) + USER_AGENT
            + struct.pack("<i", 0) + b"\0")


def parse_version(p: bytes) -> dict:
    ver, services, _ts = struct.unpack_from("<iQq", p, 0)
    i = 20 + 26 + 26 + 8
    n, i = read_varint(p, i)
    ua = p[i:i + n].decode("utf-8", "replace")
    i += n
    height = struct.unpack_from("<i", p, i)[0] if len(p) >= i + 4 else None
    return {"version": ver, "services": services, "user_agent": ua, "height": height}


def fmt_ip16(b: bytes) -> tuple[str, str]:
    if b[:12] == b"\0" * 10 + b"\xff\xff":
        return "ipv4", str(ipaddress.IPv4Address(b[12:]))
    return "ipv6", str(ipaddress.IPv6Address(b))


def parse_addr(p: bytes) -> list[tuple]:
    out = []
    n, i = read_varint(p, 0)
    for _ in range(n):
        t, _svc = struct.unpack_from("<IQ", p, i)
        net, host = fmt_ip16(p[i + 12:i + 28])
        port = struct.unpack_from(">H", p, i + 28)[0]
        out.append((net, host, port, t))
        i += 30
    return out


def parse_addrv2(p: bytes) -> list[tuple]:
    out = []
    n, i = read_varint(p, 0)
    for _ in range(n):
        t = struct.unpack_from("<I", p, i)[0]
        _svc, i = read_varint(p, i + 4)
        netid = p[i]
        alen, i = read_varint(p, i + 1)
        raw = p[i:i + alen]
        i += alen
        port = struct.unpack_from(">H", p, i)[0]
        i += 2
        net = NET_IDS.get(netid, f"net{netid}")
        if net == "ipv4" and alen == 4:
            host = str(ipaddress.IPv4Address(raw))
        elif net == "ipv6" and alen == 16:
            net, host = fmt_ip16(raw)  # also catches v4-mapped
        else:
            host = raw.hex()
        out.append((net, host, port, t))
    return out


async def read_msg(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    hdr = await reader.readexactly(24)
    if hdr[:4] != MAGIC:
        raise ValueError("bad magic")
    cmd = hdr[4:16].rstrip(b"\0").decode("ascii", "replace")
    (length,) = struct.unpack_from("<I", hdr, 16)
    if length > 4_000_000:
        raise ValueError("oversized message")
    payload = await reader.readexactly(length)
    return cmd, payload


# probe
async def probe(host: str, port: int) -> tuple[dict, list[tuple]]:
    rec: dict = {"host": host, "port": port, "t": int(time.time())}
    addrs: list[tuple] = []
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        writer.write(msg("version", version_payload(host, port)))
        await writer.drain()
        got_version = got_verack = False

        async def handshake():
            nonlocal got_version, got_verack
            while not (got_version and got_verack):
                cmd, p = await read_msg(reader)
                if cmd == "version":
                    rec.update(parse_version(p))
                    got_version = True
                    writer.write(msg("sendaddrv2") + msg("verack"))
                    await writer.drain()
                elif cmd == "verack":
                    got_verack = True

        await asyncio.wait_for(handshake(), HANDSHAKE_TIMEOUT)
        rec["status"] = "ok"
        writer.write(msg("getaddr"))
        await writer.drain()
        deadline = time.monotonic() + GETADDR_WINDOW
        while (left := deadline - time.monotonic()) > 0:
            try:
                cmd, p = await asyncio.wait_for(read_msg(reader), left)
            except asyncio.TimeoutError:
                break
            if cmd == "ping":
                writer.write(msg("pong", p))
                await writer.drain()
            elif cmd in ("addr", "addrv2"):
                batch = parse_addr(p) if cmd == "addr" else parse_addrv2(p)
                addrs.extend(batch)
                if len(batch) > 100:  # the getaddr answer arrives in one big message
                    break
    except asyncio.TimeoutError:
        rec.setdefault("status", "timeout")
    except ConnectionRefusedError:
        rec["status"] = "refused"
    except (OSError, asyncio.IncompleteReadError, ValueError, struct.error, IndexError) as e:
        rec.setdefault("status", "error:" + type(e).__name__)
    finally:
        if rec.get("status") == "ok":
            rec["n_addr"] = len(addrs)
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception:
                pass
    return rec, addrs


# crawl
async def crawl() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    start = int(time.time())
    base = OUT / f"crawl_{start}"
    seen: set[tuple[str, int]] = set()
    overlay: dict[str, dict] = {}
    queue: asyncio.Queue = asyncio.Queue()
    timeouts: list[tuple[str, int]] = []
    stats = {"seed_endpoints": 0, "gossip_ip_total": 0, "gossip_ip_too_old": 0}

    for seed in DNS_SEEDS:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(seed, 8333, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for fam, *_rest, sa in infos:
            key = (sa[0], 8333)
            if key not in seen:
                seen.add(key)
                queue.put_nowait(key)
                stats["seed_endpoints"] += 1

    out = open(f"{base}.jsonl", "w")
    sem_done = 0

    def enqueue(addrs: list[tuple], now: int) -> None:
        for net, host, port, t in addrs:
            if net in ("ipv4", "ipv6"):
                stats["gossip_ip_total"] += 1
                if now - t > MAX_ADDR_AGE:
                    stats["gossip_ip_too_old"] += 1
                    continue
                try:
                    ipa = ipaddress.ip_address(host)
                except ValueError:
                    continue
                if not ipa.is_global or port == 0:
                    continue
                key = (host, port)
                if key not in seen:
                    seen.add(key)
                    queue.put_nowait(key)
            else:
                o = overlay.setdefault(f"{net}:{host}:{port}", {"net": net, "first_t": t, "n": 0})
                o["n"] += 1

    async def worker(retry_pass: bool) -> None:
        nonlocal sem_done
        while True:
            try:
                host, port = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            rec, addrs = await probe(host, port)
            rec["pass"] = 2 if retry_pass else 1
            if rec["status"] == "timeout" and not retry_pass:
                timeouts.append((host, port))
            out.write(json.dumps(rec) + "\n")
            enqueue(addrs, int(time.time()))
            sem_done += 1
            if sem_done % 2000 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] probed={sem_done} queued={queue.qsize()} "
                      f"seen={len(seen)} overlay={len(overlay)}", file=sys.stderr, flush=True)

    # First pass. Workers stop as soon as the queue is empty for a moment,
    # so we keep starting them until nothing new turns up.
    while not queue.empty():
        await asyncio.gather(*(worker(False) for _ in range(CONCURRENCY)))
    # Second pass: try every timeout once more, in case it was just a lost packet.
    for k in timeouts:
        queue.put_nowait(k)
    while not queue.empty():
        await asyncio.gather(*(worker(True) for _ in range(CONCURRENCY)))
    out.close()

    with open(f"{base}_overlay.json", "w") as f:
        json.dump(overlay, f)
    meta = dict(start_utc=start, end_utc=int(time.time()), dns_seeds=DNS_SEEDS,
                concurrency=CONCURRENCY, connect_timeout=CONNECT_TIMEOUT,
                handshake_timeout=HANDSHAKE_TIMEOUT, getaddr_window=GETADDR_WINDOW,
                max_addr_age_s=MAX_ADDR_AGE, user_agent=USER_AGENT.decode(),
                probed_endpoints=len(seen), overlay_addresses=len(overlay),
                retried_timeouts=len(timeouts), **stats)
    with open(f"{base}_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    os.chdir(ROOT)
    asyncio.run(crawl())
