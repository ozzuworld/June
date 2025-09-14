#!/usr/bin/env python3
"""
Nginx-edge routing diagnostic (friendlier & deeper)

What’s new:
- Detects if the response was handled by your edge (x-edge header).
- Distinguishes Google Frontend 404 vs Nginx responses.
- Shows redirect targets and concise header preview.
- Adds /health and /_ah/health checks, plus /__edge_dump if you added it.
- Tests direct vs via-edge for orchestrator (and optional STT/TTS).
- Concurrent execution for speed, and a clean summary at the end.

Override base URLs with env vars if needed:
  EDGE_BASE=https://your-edge     (defaults to current)
  ORCH_BASE=https://your-orch
  IDP_BASE=https://your-idp
  STT_BASE=https://your-stt       (optional)
  TTS_BASE=https://your-tts       (optional)
"""

import os
import asyncio
import json
from dataclasses import dataclass
from typing import Optional, Dict, List

import httpx

# --- Defaults (override with environment variables if needed) ---
EDGE_BASE = os.getenv("EDGE_BASE", "https://nginx-edge-359243954.us-central1.run.app")
ORCH_BASE = os.getenv("ORCH_BASE", "https://june-orchestrator-359243954.us-central1.run.app")
IDP_BASE  = os.getenv("IDP_BASE",  "https://june-idp-359243954.us-central1.run.app")
STT_BASE  = os.getenv("STT_BASE",  "https://june-stt-359243954.us-central1.run.app")
TTS_BASE  = os.getenv("TTS_BASE",  "https://june-tts-359243954.us-central1.run.app")

FOLLOW_REDIRECTS = False
TIMEOUT_SECONDS = 15.0
MAX_CONCURRENCY = 8

# How many characters of body to preview for non-JSON
PREVIEW_LEN = 220

@dataclass
class TestCase:
    name: str
    url: str
    kind: str  # "edge" | "direct" | "info"
    expect: Optional[int] = None  # expected status (optional)

@dataclass
class TestResult:
    name: str
    url: str
    status: Optional[int]
    headers: Dict[str, str]
    content_type: str
    edge_handled: bool
    redirect_to: Optional[str]
    body_snippet: str
    json_body: Optional[dict]
    error: Optional[str]
    note: str


def classify_edge(headers: Dict[str, str]) -> bool:
    # We add `add_header X-Edge nginx-edge always;` in the Nginx config.
    # If present, we know the request reached our server block.
    return "x-edge" in {k.lower() for k in headers.keys()}


def is_gfe_404(status: Optional[int], headers: Dict[str, str], edge_handled: bool) -> bool:
    # Google Frontend 404s typically have Server: Google Frontend and NO x-edge.
    server = headers.get("server", "") or headers.get("Server", "")
    return (status == 404) and (not edge_handled) and ("Google Frontend" in server)


def skim_headers(h: Dict[str, str]) -> Dict[str, str]:
    # Show the key bits without overwhelming the output
    keys = ["server", "content-type", "location", "x-edge", "x-cloud-trace-context", "referrer-policy"]
    skim = {}
    for k, v in h.items():
        lk = k.lower()
        if lk in keys:
            skim[lk] = v
    return skim


async def fetch(client: httpx.AsyncClient, tc: TestCase) -> TestResult:
    try:
        resp = await client.get(tc.url)
        hdrs = dict(resp.headers)
        edge = classify_edge(hdrs)
        ctype = hdrs.get("content-type", "unknown")
        is_redirect = 300 <= resp.status_code < 400
        loc = hdrs.get("location") if is_redirect else None

        json_body = None
        body_snippet = ""
        note = ""

        if "json" in ctype.lower():
            try:
                json_body = resp.json()
            except Exception:
                body_snippet = (resp.text or "")[:PREVIEW_LEN]
        else:
            # Small snippet to see the shape of the body
            body_snippet = (resp.text or "")[:PREVIEW_LEN]

        if is_gfe_404(resp.status_code, hdrs, edge):
            note = "❗ Looks like a Google Frontend 404 (edge likely didn’t handle this path)."

        # Expectations (optional)
        if tc.expect is not None and resp.status_code != tc.expect:
            note = (note + " " if note else "") + f"Expected {tc.expect}."

        return TestResult(
            name=tc.name,
            url=tc.url,
            status=resp.status_code,
            headers=skim_headers(hdrs),
            content_type=ctype,
            edge_handled=edge,
            redirect_to=loc,
            body_snippet=body_snippet,
            json_body=json_body,
            error=None,
            note=note
        )
    except Exception as e:
        return TestResult(
            name=tc.name, url=tc.url, status=None, headers={},
            content_type="unknown", edge_handled=False, redirect_to=None,
            body_snippet="", json_body=None, error=str(e), note="❌ Request failed"
        )


def print_result(tr: TestResult) -> None:
    print(f"\n🧪 {tr.name}: {tr.url}")
    if tr.error:
        print(f"   ❌ Error: {tr.error}")
        return

    edge_flag = "✅ via EDGE" if tr.edge_handled else "⛔ not via EDGE"
    print(f"   Status: {tr.status}   ({edge_flag})")
    if tr.redirect_to:
        print(f"   ↪ Redirects to: {tr.redirect_to}")
    print(f"   Headers: {json.dumps(tr.headers, indent=2)}")
    print(f"   Content-Type: {tr.content_type}")

    if tr.json_body is not None:
        print("   Content (JSON):")
        print(json.dumps(tr.json_body, indent=2))
    elif tr.body_snippet:
        print(f"   Content (preview): {tr.body_snippet!r}")

    if tr.note:
        print(f"   Note: {tr.note}")


def print_summary(all_results: List[TestResult]) -> None:
    print("\n📊 Summary")
    print("──────────")
    for r in all_results:
        status = r.status if r.status is not None else "ERR"
        edge = "EDGE" if r.edge_handled else "—"
        marker = "✅" if (r.status and 200 <= r.status < 300) else ("↪" if (r.status and 300 <= r.status < 400) else "⚠️")
        print(f"{marker} {r.name:<35} {status:<4} {edge:<4} {r.url}")

    # Helpful conclusions
    print("\n🔎 Quick conclusions")
    health_edge = [r for r in all_results if r.name == "edge /healthz"]
    if health_edge:
        r = health_edge[0]
        if r.status == 200 and r.edge_handled:
            print("• Edge health: ✅ /healthz is served by your Nginx (good).")
        elif r.status == 404 and not r.edge_handled:
            print("• Edge health: ❌ /healthz looks like a Google Frontend 404. Your edge didn’t match this path.")
            print("  → Ensure your conf.d file is actually loaded (add /__edge_dump, build from services/nginx-edge, see logs for `nginx -T`).")
        else:
            print("• Edge health: ⚠️ Unexpected status or missing x-edge; double-check config and build context.")

    # Note about orchestrator health
    orch_h = [r for r in all_results if r.name == "orchestrator /healthz (direct)"]
    if orch_h and orch_h[0].status == 404:
        print("• Orchestrator /healthz: 404 (expected if the app doesn’t implement it). Not an edge problem.")

    print("\n💡 Tip: If you added `location = /__edge_dump { return 200 \"edge-conf-live:v1\\n\"; }`,")
    print("        then hitting /__edge_dump should return that marker WITH the x-edge header.")


async def main() -> None:
    print("🔍 Nginx Routing Diagnostic")
    print("=" * 50)

    tests: List[TestCase] = []

    # Edge self checks
    tests += [
        TestCase("edge /healthz",         f"{EDGE_BASE}/healthz", kind="edge"),
        TestCase("edge /health",          f"{EDGE_BASE}/health",  kind="edge"),
        TestCase("edge /_ah/health",      f"{EDGE_BASE}/_ah/health", kind="edge"),
        TestCase("edge / (root)",         f"{EDGE_BASE}/",        kind="edge"),
        TestCase("edge /__edge_dump",     f"{EDGE_BASE}/__edge_dump", kind="edge"),  # optional, if present
    ]

    # Direct services (bypass edge)
    tests += [
        TestCase("orchestrator / (direct)",      f"{ORCH_BASE}/",      kind="direct"),
        TestCase("orchestrator /healthz (direct)", f"{ORCH_BASE}/healthz", kind="direct"),
    ]

    # Through the edge
    tests += [
        TestCase("orchestrator via edge /",      f"{EDGE_BASE}/orchestrator/", kind="edge"),
        TestCase("orchestrator via edge /healthz", f"{EDGE_BASE}/orchestrator/healthz", kind="edge"),
    ]

    # Keycloak sanity
    tests += [
        TestCase("keycloak /realms/june (direct)", f"{IDP_BASE}/realms/june", kind="direct"),
        TestCase("keycloak via edge /auth/realms/june", f"{EDGE_BASE}/auth/realms/june", kind="edge"),
    ]

    # Optional STT/TTS if you want quick signal (root paths may 404 which is OK if consistent)
    if STT_BASE:
        tests.append(TestCase("stt / (direct)", f"{STT_BASE}/", kind="direct"))
        tests.append(TestCase("stt via edge /", f"{EDGE_BASE}/stt/", kind="edge"))
    if TTS_BASE:
        tests.append(TestCase("tts / (direct)", f"{TTS_BASE}/", kind="direct"))
        tests.append(TestCase("tts via edge /", f"{EDGE_BASE}/tts/", kind="edge"))

    limits = httpx.Limits(max_keepalive_connections=MAX_CONCURRENCY, max_connections=MAX_CONCURRENCY)
    async with httpx.AsyncClient(http2=True, timeout=TIMEOUT_SECONDS, follow_redirects=FOLLOW_REDIRECTS, limits=limits) as client:
        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        async def run(tc: TestCase):
            async with sem:
                return await fetch(client, tc)

        results = await asyncio.gather(*(run(tc) for tc in tests))

    for r in results:
        print_result(r)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
