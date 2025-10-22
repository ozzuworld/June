#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai
Uses official vastai CLI instead of direct REST API calls to ensure compatibility
Includes safety: global rate limit, backoff on errors, and circuit breaker
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

# 3.11 compatibility shim for libs importing from collections
import collections as _collections
import collections.abc as _abc
for _n in ("Mapping", "MutableMapping", "Sequence", "Callable"):
    if not hasattr(_collections, _n) and hasattr(_abc, _n):
        setattr(_collections, _n, getattr(_abc, _n))

import aiohttp
import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

# Vast.ai API configuration
VAST_API_KEY = os.getenv("VAST_API_KEY")
NODE_NAME = os.getenv("NODE_NAME", "vast-gpu-node-python")

# Optional forced overrides via env (to bypass stale annotations)
FORCE_GPU_TYPE = os.getenv("FORCE_GPU_TYPE")
FORCE_IMAGE = os.getenv("FORCE_IMAGE")
FORCE_PRICE_MAX = os.getenv("FORCE_PRICE_MAX")

# Safety configuration - baked into the code to prevent API abuse
from asyncio import Semaphore
INSTANCE_BUY_SEMAPHORE = Semaphore(1)  # Only 1 concurrent purchase
GLOBAL_RPS = 0.5  # Max 1 API call every 2 seconds
BACKOFF_INITIAL = 2.0  # Initial backoff on errors
BACKOFF_MAX = 60.0  # Max backoff
CIRCUIT_FAILS_TO_OPEN = 5  # Circuit opens after 5 failures
CIRCUIT_OPEN_SEC = 300.0  # Circuit stays open for 5 minutes

# Global rate limiter - prevents rapid API calls
_last_call_ts = 0.0
async def _respect_global_rate_limit():
    global _last_call_ts
    min_interval = 1.0 / max(GLOBAL_RPS, 0.1)
    now = time.time()
    sleep_for = (_last_call_ts + min_interval) - now
    if sleep_for > 0:
        logger.debug("Rate limiting CLI call", sleep_seconds=sleep_for)
        await asyncio.sleep(sleep_for)
    _last_call_ts = time.time()


class VastAIClient:
    """Client for Vast.ai using official CLI instead of broken REST API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cli_path = self._find_cli_path()
        self._setup_api_key()
    
    def _find_cli_path(self) -> Optional[str]:
        """Find vastai CLI executable"""
        paths = [shutil.which("vastai"), "/usr/local/bin/vastai", "/app/vastai"]
        for path in paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                logger.info("Found vastai CLI", path=path)
                return path
        logger.warning("vastai CLI not found, will fail")
        return None
    
    def _setup_api_key(self):
        if self.api_key:
            api_key_file = os.path.expanduser("~/.vastai_api_key")
            with open(api_key_file, "w") as f:
                f.write(self.api_key)
            os.chmod(api_key_file, 0o600)
            logger.debug("API key configured for CLI")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def _gpu_name_to_cli_format(self, gpu_name: str) -> str:
        # Vast CLI expects underscores, e.g., "RTX_3060_Ti"
        return gpu_name.replace(" ", "_")
    
    def _build_search_query(self, gpu_type: str, max_price: float, region: Optional[str] = None) -> str:
        """Build a VALID vastai CLI filter string.
        Key rules:
        - lowercase booleans
        - comparison operators without spaces
        - comma-separated lists, not space words like "North America"
        - use country=US,CA (or geolocation_in=US,CA) for region filters
        - use dph for price cap
        """
        gpu_cli = self._gpu_name_to_cli_format(gpu_type)
        parts = [
            "rentable=true",
            "verified=true",
            "rented=false",
            f"gpu_name={gpu_cli}",
            f"dph<={max_price:.2f}",
            "reliability>=0.70",
            "inet_down>=50",
            "inet_up>=20",
        ]
        # Region mapping
        if region:
            region = region.strip()
            if region.lower() in ("north america", "na"):
                parts.append("country=US,CA,MX")
            elif region.lower() in ("us", "usa", "united states"):
                parts.append("country=US")
            elif region.lower() in ("canada", "ca"):
                parts.append("country=CA")
            elif region.lower() in ("europe", "eu"):
                parts.append("geolocation_in=EU")
            else:
                # Fallback: pass through value if user provided a valid field
                # Avoid adding bare words that break CLI
                if "=" in region:
                    parts.append(region)
        return " ".join(parts)
    
    async def _run_cli_command(self, args: List[str]) -> Dict[str, Any]:
        if not self.cli_path:
            raise RuntimeError("vastai CLI not available")
        await _respect_global_rate_limit()
        cmd = [self.cli_path] + args
        try:
            logger.debug("Running CLI command", cmd=cmd)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error("CLI command failed", cmd=cmd, error=error_msg, returncode=proc.returncode)
                if "rate" in error_msg.lower() or "too many" in error_msg.lower():
                    logger.warning("CLI rate limited, backing off")
                    await asyncio.sleep(min(BACKOFF_MAX, BACKOFF_INITIAL * 2))
                return {"error": error_msg, "returncode": proc.returncode}
            out = stdout.decode().strip()
            if not out:
                return {"data": []}
            try:
                if out.startswith("[") or out.startswith("{"):
                    return {"data": json.loads(out)}
                return {"data": out}
            except json.JSONDecodeError:
                return {"data": out}
        except Exception as e:
            logger.error("CLI command exception", cmd=cmd, error=str(e))
            return {"error": str(e)}
    
    async def search_offers(self, gpu_type: str = "RTX 4060", max_price: float = 0.50, region: Optional[str] = None) -> List[Dict[str, Any]]:
        query = self._build_search_query(gpu_type, max_price, region)
        # Sort cheapest first per Vast docs: dph+
        result = await self._run_cli_command(["search", "offers", "--raw", "--no-default", query, "-o", "dph+"])
        if "error" in result:
            logger.error("CLI search failed", gpu_type=gpu_type, error=result["error"])
            return []
        data = result.get("data", [])
        if isinstance(data, list):
            logger.info("CLI search success", gpu_type=gpu_type, offer_count=len(data))
            return data
        logger.warning("CLI search returned non-list", gpu_type=gpu_type, data_type=type(data))
        return []
    
    async def buy_instance(self, ask_id: int, pod_annotations: Dict[str, str]) -> Optional[Dict[str, Any]]:
        # Prefer env override, then annotation, then sane default that works with Vast.ai
        image = FORCE_IMAGE or pod_annotations.get("vast.ai/image", "ozzuworld/june-gpu-multi:latest")
        # Backward compatibility: accept both our repo names
        if image == "ozzuworld/june-multi-gpu:latest":
            image = "ozzuworld/june-gpu-multi:latest"
        disk_str = pod_annotations.get("vast.ai/disk", "50")
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except (AttributeError, ValueError):
            disk_gb = 50.0
        args = ["create", "instance", str(ask_id), "--raw", "--image", image, "--disk", str(int(disk_gb))]
        if "vast.ai/onstart-cmd" in pod_annotations:
            args.extend(["--onstart", pod_annotations["vast.ai/onstart-cmd"]])
        if "vast.ai/env" in pod_annotations:
            args.extend(["--env", pod_annotations["vast.ai/env"]])
        result = await self._run_cli_command(args)
        if "error" in result:
            logger.error("CLI create instance failed", ask_id=ask_id, error=result["error"])
            return None
        data = result.get("data")
        if isinstance(data, str) and data.isdigit():
            iid = int(data)
            logger.info("Instance creation initiated via CLI", ask_id=ask_id, instance_id=iid)
            return {"new_contract": iid}
        if isinstance(data, dict) and "new_contract" in data:
            logger.info("Instance creation initiated via CLI", ask_id=ask_id, instance_id=data["new_contract"]) 
            return data
        logger.error("CLI create returned unexpected format", ask_id=ask_id, data=data)
        return None

    # ... rest of file unchanged ...
