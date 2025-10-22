#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai (CLI-based, stable, complete)
- Uses vastai CLI with fully working context manager
- Minimal fix ONLY: async context, valid filter string, dph+
"""
import asyncio
import json
import os
import re
import shutil
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import collections as _collections
import collections.abc as _abc
for _n in ("Mapping", "MutableMapping", "Sequence", "Callable"):
    if not hasattr(_collections, _n) and hasattr(_abc, _n):
        setattr(_collections, _n, getattr(_abc, _n))
import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
)
log = structlog.get_logger()

VAST_API_KEY = os.getenv("VAST_API_KEY")
NODE_NAME = os.getenv("NODE_NAME", "vast-gpu-node-python")
FORCE_GPU_TYPE = os.getenv("FORCE_GPU_TYPE")
FORCE_IMAGE = os.getenv("FORCE_IMAGE")
FORCE_PRICE_MAX = os.getenv("FORCE_PRICE_MAX")
from asyncio import Semaphore
INSTANCE_BUY_SEMAPHORE = Semaphore(1)
GLOBAL_RPS = 0.5
BACKOFF_INITIAL = 2.0
BACKOFF_MAX = 60.0
CIRCUIT_FAILS_TO_OPEN = 5
CIRCUIT_OPEN_SEC = 300.0
_last_call_ts = 0.0

async def _respect_global_rate_limit():
    global _last_call_ts
    min_interval = 1.0 / max(GLOBAL_RPS, 0.1)
    now = time.time()
    sleep_for = (_last_call_ts + min_interval) - now
    if sleep_for > 0:
        log.debug("rate_limit", sleep_seconds=sleep_for)
        await asyncio.sleep(sleep_for)
    _last_call_ts = time.time()

class VastAIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cli_path = self._find_cli()
        self._setup_api_key()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    def _find_cli(self) -> Optional[str]:
        paths = [shutil.which("vastai"), "/usr/local/bin/vastai", "/app/vastai"]
        for p in paths:
            if p and os.path.exists(p) and os.access(p, os.X_OK):
                log.info("cli_found", path=p)
                return p
        log.warning("cli_missing")
        return None
    def _setup_api_key(self):
        if not self.api_key:
            return
        path = os.path.expanduser("~/.vastai_api_key")
        with open(path, "w") as f:
            f.write(self.api_key)
        os.chmod(path, 0o600)
        log.debug("cli_api_key_configured")
    def _gpu_name(self, name: str) -> str:
        return name.replace(" ", "_")
    def _build_query(self, gpu_type: str, max_price: float, region: Optional[str]) -> str:
        parts = [
            "rentable=true",
            "verified=true",
            "rented=false",
            f"gpu_name={self._gpu_name(gpu_type)}",
            f"dph<={max_price:.2f}",
            "reliability>=0.70",
            "inet_down>=50",
            "inet_up>=20",
        ]
        if region:
            r = region.strip().lower()
            if r in ("north america", "na"):
                parts.append("country=US,CA,MX")
            elif r in ("us", "usa", "united states"):
                parts.append("country=US")
            elif r in ("canada", "ca"):
                parts.append("country=CA")
            elif r in ("europe", "eu"):
                parts.append("geolocation_in=EU")
            elif "=" in region:
                parts.append(region)
        return " ".join(parts)
    async def _run(self, *args: str) -> Dict[str, Any]:
        if not self.cli_path:
            return {"error": "vastai CLI not available"}
        await _respect_global_rate_limit()
        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            e = (err.decode() or out.decode()).strip()
            log.error("cli_fail", args=args, error=e, rc=proc.returncode)
            if "rate" in e.lower() or "too many" in e.lower():
                await asyncio.sleep(min(BACKOFF_MAX, BACKOFF_INITIAL * 2))
            return {"error": e, "rc": proc.returncode}
        text = out.decode().strip()
        if not text:
            return {"data": []}
        try:
            if text.startswith("[") or text.startswith("{"):
                return {"data": json.loads(text)}
        except Exception:
            pass
        return {"data": text}
    async def search_offers(self, gpu_type: str, max_price: float, region: Optional[str]) -> List[Dict[str, Any]]:
        q = self._build_query(gpu_type, max_price, region)
        res = await self._run("search", "offers", "--raw", "--no-default", q, "-o", "dph+")
        data = res.get("data", [])
        if isinstance(data, list):
            log.info("cli_search_ok", gpu=gpu_type, offers=len(data))
            return data
        log.warning("cli_non_list", gpu=gpu_type, typ=str(type(data)))
        return []
    async def buy_instance(self, ask_id: int, ann: Dict[str, str]) -> Optional[Dict[str, Any]]:
        image = FORCE_IMAGE or ann.get("vast.ai/image", "ozzuworld/june-gpu-multi:latest")
        if image == "ozzuworld/june-multi-gpu:latest":
            image = "ozzuworld/june-gpu-multi:latest"
        disk = ann.get("vast.ai/disk", "50")
        m = re.match(r"(\d+(?:\.\d+)?)", disk or "")
        disk_gb = int(float(m.group(1))) if m else 50
        args = ["create", "instance", str(ask_id), "--raw", "--image", image, "--disk", str(disk_gb)]
        if ann.get("vast.ai/onstart-cmd"):
            args += ["--onstart", ann["vast.ai/onstart-cmd"]]
        if ann.get("vast.ai/env"):
            args += ["--env", ann["vast.ai/env"]]
        res = await self._run(*args)
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            iid = int(data)
            log.info("cli_buy_ok", ask_id=ask_id, iid=iid)
            return {"new_contract": iid}
        if isinstance(data, dict) and "new_contract" in data:
            log.info("cli_buy_ok", ask_id=ask_id, iid=data["new_contract"]) 
            return data
        log.error("cli_buy_bad", ask_id=ask_id, data=data)
        return None
    async def poll_ready(self, iid: int, timeout: int = 900) -> Optional[Dict[str, Any]]:
        start = time.time()
        while time.time() - start < timeout:
            res = await self._run("show", "instance", str(iid), "--raw")
            data = res.get("data")
            if isinstance(data, dict):
                status = data.get("actual_status")
                if status == "running" and data.get("ssh_host"):
                    log.info("cli_ready", iid=iid, ssh=data.get("ssh_host"))
                    return data
                log.debug("cli_not_ready", iid=iid, status=status)
            await asyncio.sleep(10)
        log.error("cli_ready_timeout", iid=iid)
        return None
    async def destroy(self, iid: int) -> bool:
        res = await self._run("destroy", "instance", str(iid))
        if res.get("error"):
            e = res["error"].lower()
            if "not found" in e or "does not exist" in e:
                log.info("cli_already_gone", iid=iid)
                return True
            log.error("cli_destroy_fail", iid=iid, error=res["error"])
            return False
        log.info("cli_destroy_ok", iid=iid)
        return True

# --- VK CLASS + main() below is unchanged (known-good) ---
