#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai
Uses official vastai CLI with improved logging and graceful handling of external deletions
"""
import asyncio
import json
import os
import re
import shutil
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from collections import defaultdict

# 3.11 compatibility shim
import collections as _collections
import collections.abc as _abc
for _n in ("Mapping", "MutableMapping", "Sequence", "Callable"):
    if not hasattr(_collections, _n) and hasattr(_abc, _n):
        setattr(_collections, _n, getattr(_abc, _n))

import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

# Logging
structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
)
logger = structlog.get_logger()

# Env/config
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

# Log suppression helpers
_error_counts: Dict[str,int] = defaultdict(int)
_last_status: Dict[int,str] = {}
_last_summary_ts: float = 0.0

async def _respect_global_rate_limit():
    global _last_call_ts
    min_interval = 1.0 / max(GLOBAL_RPS, 0.1)
    now = time.time()
    sleep_for = (_last_call_ts + min_interval) - now
    if sleep_for > 0:
        logger.debug("rate_limit", sleep_seconds=sleep_for)
        await asyncio.sleep(sleep_for)
    _last_call_ts = time.time()

class VastAIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cli_path = self._find_cli_path()
        self._setup_api_key()

    def _find_cli_path(self) -> Optional[str]:
        paths = [shutil.which("vastai"), "/usr/local/bin/vastai", "/app/vastai"]
        for p in paths:
            if p and os.path.exists(p) and os.access(p, os.X_OK):
                logger.info("cli_found", path=p)
                return p
        logger.warning("cli_missing")
        return None

    def _setup_api_key(self):
        if not self.api_key:
            return
        path = os.path.expanduser("~/.vastai_api_key")
        with open(path, "w") as f:
            f.write(self.api_key)
        os.chmod(path, 0o600)
        logger.debug("cli_api_key_configured")

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
            r = (region or '').strip().lower()
            if r in ("north america", "na"):
                parts.append("geolocation in [US,CA,MX]")
            elif r in ("us", "usa", "united states"):
                parts.append("geolocation=US")
            elif r in ("canada", "ca"):
                parts.append("geolocation=CA")
            elif r in ("europe", "eu"):
                parts.append("geolocation in [DE,FR,GB,IT,ES]")
            elif "=" in region:
                parts.append(region)
        return " ".join(parts)

    async def _run(self, *args: str, op: str = "poll") -> Dict[str, Any]:
        if not self.cli_path:
            return {"error": "vastai CLI not available"}
        await _respect_global_rate_limit()
        cmd = [self.cli_path, *args]
        # Only info-log non-poll operations; poll at debug
        if op != "poll":
            logger.info("cli_run", cmd=cmd, op=op)
        else:
            logger.debug("cli_poll", cmd=cmd[:3])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            e = (err.decode() or out.decode()).strip()
            # throttle repeated errors
            key = op + ":" + " ".join(args[:3])
            if _error_counts[key] < 3:
                logger.error("cli_fail", op=op, args=args, error=e, rc=proc.returncode)
                _error_counts[key] += 1
            elif _error_counts[key] == 3:
                logger.warning("cli_fail_suppressed", op=op, args=args[:3])
                _error_counts[key] += 1
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
        res = await self._run("search", "offers", "--raw", "--no-default", q, "-o", "dph+", op="search")
        data = res.get("data", [])
        if isinstance(data, list):
            logger.info("cli_search_ok", gpu=gpu_type, offers=len(data))
            return data
        logger.warning("cli_non_list", gpu=gpu_type, typ=str(type(data)))
        return []

    async def buy_instance(self, ask_id: int, ann: Dict[str, str]) -> Optional[Dict[str, Any]]:
        image = FORCE_IMAGE or ann.get("vast.ai/image", "ozzuworld/june-gpu-multi:latest")
        disk = ann.get("vast.ai/disk", "50")
        m = re.match(r"(\d+(?:\.\d+)?)", disk or "")
        disk_gb = int(float(m.group(1))) if m else 50
        args = ["create", "instance", str(ask_id), "--raw", "--image", image, "--disk", str(disk_gb)]
        if ann.get("vast.ai/onstart-cmd"):
            args += ["--onstart-cmd", ann["vast.ai/onstart-cmd"]]
        if ann.get("vast.ai/env"):
            args += ["--env", ann["vast.ai/env"]]
        res = await self._run(*args, op="create")
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            iid = int(data)
            logger.info("cli_buy_ok", ask_id=ask_id, iid=iid)
            return {"new_contract": iid}
        if isinstance(data, dict) and "new_contract" in data:
            logger.info("cli_buy_ok", ask_id=ask_id, iid=data["new_contract"]) 
            return data
        if res.get("error"):
            logger.error("cli_buy_bad", ask_id=ask_id, error=res.get("error"))
        else:
            logger.error("cli_buy_bad", ask_id=ask_id, data=data)
        return None

    async def poll_ready(self, iid: int, timeout: int = 900) -> Optional[Dict[str, Any]]:
        start = time.time()
        while time.time() - start < timeout:
            res = await self._run("show", "instance", str(iid), "--raw", op="poll")
            if "error" in res:
                msg = res["error"].lower()
                if any(k in msg for k in ["not found", "does not exist", "unknown instance"]):
                    logger.info("cli_gone", iid=iid)
                    return {"gone": True}
                if "start_date" in msg and "none" in msg:
                    await asyncio.sleep(10)
                    continue
                await asyncio.sleep(10)
                continue
            data = res.get("data")
            if isinstance(data, dict):
                status = data.get("actual_status")
                # log only on change
                prev = _last_status.get(iid)
                if status != prev:
                    logger.info("cli_status", iid=iid, status=status)
                    _last_status[iid] = status
                if status == "running" and data.get("ssh_host"):
                    logger.info("cli_ready", iid=iid, ssh=data.get("ssh_host"))
                    return data
            await asyncio.sleep(10)
        logger.error("cli_ready_timeout", iid=iid)
        return None

    async def destroy(self, iid: int) -> bool:
        res = await self._run("destroy", "instance", str(iid), op="destroy")
        if res.get("error"):
            e = res["error"].lower()
            if "not found" in e or "does not exist" in e:
                logger.info("cli_already_gone", iid=iid)
                return True
            logger.error("cli_destroy_fail", iid=iid, error=res["error"])
            return False
        logger.info("cli_destroy_ok", iid=iid)
        return True

class VirtualKubelet:
    ...
    # Keep the rest of your existing VK class unchanged except for create_pod handling of gone
    async def create_pod(self, pod):
        name = pod.metadata.name
        logger.info("create_pod", pod=name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_status_failed(pod, "No GPU instances available via CLI")
                    return
                async with INSTANCE_BUY_SEMAPHORE:
                    res = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})
                if not res:
                    await self.update_pod_status_failed(pod, "Failed to create instance via CLI")
                    return
                iid = int(res.get("new_contract"))
                ready = await vast.poll_ready(iid, timeout=900)
                if not ready:
                    await vast.destroy(iid)
                    await self.update_pod_status_failed(pod, "Instance failed to start via CLI")
                    return
                if ready.get("gone"):
                    await self.update_pod_status_failed(pod, "Instance deleted externally via Vast console")
                    return
                instance = {
                    "id": iid,
                    "status": "running",
                    "public_ip": ready.get("public_ipaddr"),
                    "ssh_port": ready.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready,
                }
                self.pod_instances[name] = instance
                await self.update_pod_status_running(pod, instance)
                logger.info("pod_created", pod=name, iid=iid)
        except Exception as e:
            logger.error("create_pod_error", pod=name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))

# The rest (HTTP, main) remains the same
