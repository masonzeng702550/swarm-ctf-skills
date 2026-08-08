#!/usr/bin/env python3
"""Probe every remote target in campaign.json and classify its blocker class.

Why this exists: two workers once burned their entire step budget independently
rediscovering that the target sits behind a Cloudflare managed challenge, which
no requests/curl-based worker can pass. Classify first, route second.

Classes:
    direct           plain HTTP reachable          -> normal worker
    cf_challenge     Cloudflare / WAF interstitial -> browser toolkit required
    auth_required    401/403 without CF markers    -> needs creds or token
    instancer        page mentions token/instance  -> mint CTFd API token first
    tcp_only         raw host:port, no HTTP        -> pwntools worker
    offline          nothing listening             -> report, do not dispatch

Usage:
    python3 .claude/skills/swarm-attack/scripts/preflight.py
    python3 .claude/skills/swarm-attack/scripts/preflight.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("error: pip install requests", file=sys.stderr)
    raise SystemExit(1)

URL_RE = re.compile(r"https?://[\w.\-]+(?::\d+)?(?:/[\w./\-?=&%#]*)?")
HOSTPORT_RE = re.compile(r"\b(?:nc\s+|tcp://)?([a-z0-9][\w.\-]*\.[a-z]{2,}|\d+\.\d+\.\d+\.\d+)[\s:]+(\d{2,5})\b")
CF_MARKERS = ("cf-mitigated", "cf-chl", "just a moment", "attention required", "challenge-platform")
INSTANCER_HINTS = ("instance", "token", "launch", "ctfd_")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def extract_targets(ch: dict, platform_host: str) -> list[str]:
    blob = f"{ch.get('description') or ''}\n{ch.get('connection_info') or ''}"
    targets: list[str] = []
    for m in URL_RE.findall(blob):
        if urlparse(m).hostname and urlparse(m).hostname != platform_host:
            targets.append(m.rstrip(".,)"))
    for host, port in HOSTPORT_RE.findall(blob):
        cand = f"{host}:{port}"
        if host != platform_host and not any(cand in t for t in targets):
            targets.append(cand)
    return list(dict.fromkeys(targets))[:4]


def probe_http(url: str, timeout: float) -> dict:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, allow_redirects=True)
    except requests.exceptions.SSLError as e:
        return {"class": "direct", "detail": f"ssl error: {str(e)[:60]}"}
    except requests.exceptions.ConnectionError:
        return {"class": "offline", "detail": "connection refused / dns failure"}
    except requests.exceptions.RequestException as e:
        return {"class": "offline", "detail": str(e)[:80]}

    head = " ".join(f"{k}:{v}" for k, v in r.headers.items()).lower()
    body = r.text[:4000].lower()
    server_cf = "cloudflare" in head

    if r.status_code in (403, 429, 503) and (server_cf or any(m in body or m in head for m in CF_MARKERS)):
        return {"class": "cf_challenge", "status": r.status_code,
                "detail": "cloudflare managed challenge - socket tooling cannot pass"}
    if any(m in body for m in CF_MARKERS):
        return {"class": "cf_challenge", "status": r.status_code, "detail": "interstitial in body"}
    if r.status_code in (401, 403):
        return {"class": "auth_required", "status": r.status_code, "detail": "no CF markers - creds/token needed"}
    if r.status_code < 400 and sum(h in body for h in INSTANCER_HINTS) >= 2:
        return {"class": "instancer", "status": r.status_code,
                "detail": "per-token instancer - mint CTFd API token, expect rate limits"}
    return {"class": "direct", "status": r.status_code, "detail": f"{len(r.content)}B"}


def probe_tcp(host: str, port: int, timeout: float) -> dict:
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            try:
                banner = s.recv(120).decode("utf-8", "replace").strip()
            except OSError:
                banner = ""
        return {"class": "tcp_only", "detail": f"open · banner={banner[:60]!r}"}
    except OSError as e:
        return {"class": "offline", "detail": str(e)[:60]}


def probe(target: str, timeout: float) -> dict:
    if target.startswith("http"):
        result = probe_http(target, timeout)
    else:
        host, _, port = target.rpartition(":")
        result = probe_tcp(host, int(port), timeout)
    result["target"] = target
    return result


ROUTING = {
    "cf_challenge": "browser toolkit: nodriver (xvfb-run, headless=False) -> cf_clearance + UA, replay via curl_cffi(impersonate='chrome131')",
    "auth_required": "supply CTFd session cookie or API token in the worker prompt",
    "instancer": "coordinator mints ONE ctfd_ API token, broadcasts it, workers take an instance lease",
    "offline": "do not dispatch - report to user, may need VPN or the challenge is down",
    "tcp_only": "pwntools worker, remote() - build a local reproducer before spending remote attempts",
    "direct": "normal dispatch",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify challenge targets before dispatch")
    ap.add_argument("--campaign", default="db/campaign.json")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = Path(args.campaign)
    if not path.exists():
        print(f"error: {path} not found - run the login step first", file=sys.stderr)
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    platform_host = urlparse(data.get("platform_url", "")).hostname or ""
    solved = set(data.get("solved_ids") or [])

    report = []
    for ch in data.get("challenges", []):
        if ch.get("id") in solved:
            continue
        targets = extract_targets(ch, platform_host)
        if not targets:
            continue
        report.append({
            "id": ch.get("id"),
            "name": ch.get("name"),
            "category": ch.get("category"),
            "probes": [probe(t, args.timeout) for t in targets],
        })

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    blocked: dict[str, list[str]] = {}
    print(f"{'Class':<15}{'Challenge':<34}Target / detail")
    print("-" * 96)
    for entry in report:
        for p in entry["probes"]:
            print(f"{p['class']:<15}{str(entry['name'])[:33]:<34}{p['target'][:40]}  {p.get('detail','')[:34]}")
            blocked.setdefault(p["class"], []).append(str(entry["name"]))
    print("\nRouting:")
    for cls, names in blocked.items():
        if cls == "direct":
            continue
        print(f"  [{cls}] {len(set(names))} challenge(s): {ROUTING[cls]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
