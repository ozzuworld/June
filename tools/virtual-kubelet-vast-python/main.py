#!/usr/bin/env python3
"""
Python-based Virtual Kubelet for Vast.ai GPU instances
Provides better debugging and error visibility than Go version
"""

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog
from aiohttp import web, ClientSession
from kubernetes import client, config, watch
from kubernetes.client import V1Node, V1Pod, V1PodStatus, V1ContainerStatus
from kubernetes.client.rest import ApiException

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


NA_SUBSTRINGS = [", US", ", CA", ", MX"]


def is_in_region(geolocation: str, region: Optional[str]) -> bool:
    if not region:
        return True
    loc = (geolocation or "").lower()
    reg = region.lower().strip()
    if reg == "north america":
        return any(suffix.lower() in loc for suffix in NA_SUBSTRINGS)
    # fallback to substring match for other regions
    return reg in loc


class VastAIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://console.vast.ai/api/v0"
        self.session: Optional[ClientSession] = None
        
    async def __aenter__(self):
        self.session = ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_connection(self) -> bool:
        logger.info("Testing Vast.ai API connection")
        try:
            if not self.session:
                raise RuntimeError("Client session not initialized")
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with self.session.get(f"{self.base_url}/users/current", headers=headers) as resp:
                if resp.status == 200:
                    logger.info("Vast.ai API connection successful")
                    return True
                else:
                    logger.error("Vast.ai API connection failed", status_code=resp.status)
                    return False
        except Exception as e:
            logger.error("Vast.ai API connection error", error=str(e))
            return False

    async def search_offers(self, q: Dict, order: List[List[str]] = None, offer_type: str = "on-demand") -> List[Dict]:
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {"q": q, "order": order or [["dph_total", "asc"]], "type": offer_type}
        try:
            async with self.session.put(f"{self.base_url}/search/asks/", headers=headers, json=body) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("offers", [])
                else:
                    txt = await resp.text()
                    logger.error("search_offers failed", status_code=resp.status, response=txt)
                    return []
        except Exception as e:
            logger.error("search_offers exception", error=str(e))
            return []


class VirtualKubelet:
    def __init__(self, node_name: str, api_key: str):
        self.node_name = node_name
        self.api_key = api_key
        self.vast_client: Optional[VastAIClient] = None
        self.k8s_client: Optional[client.CoreV1Api] = None
        self.pod_instances: Dict[str, Dict] = {}
        self.running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._poller_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        logger.info("Initializing Virtual Kubelet", node_name=self.node_name)
        try:
            logger.info("Loading Kubernetes config")
            config.load_incluster_config()
            self.k8s_client = client.CoreV1Api()
            logger.info("Kubernetes client initialized")
            logger.info("Initializing Vast.ai client")
            self.vast_client = VastAIClient(self.api_key)
            async with self.vast_client as vast:
                if not await vast.test_connection():
                    raise RuntimeError("Failed to connect to Vast.ai API")
            await self.register_node()
            logger.info("Virtual Kubelet initialization complete")
        except Exception as e:
            logger.error("Failed to initialize Virtual Kubelet", error=str(e))
            raise

    def _parse_annotations(self, pod: V1Pod) -> Tuple[List[str], Optional[float], Optional[str]]:
        ann = pod.metadata.annotations or {}
        primary = ann.get("vast.ai/gpu-type", "RTX 3060").replace("_", " ").strip()
        fallbacks = ann.get("vast.ai/gpu-fallbacks", "RTX 3060 Ti,RTX 4060,RTX 4070,RTX 3090,RTX A5000")
        fallback_list = [primary] + [g.strip() for g in fallbacks.split(",") if g.strip()]
        price_max = ann.get("vast.ai/price-max")
        region = ann.get("vast.ai/region")
        return fallback_list, float(price_max) if price_max else None, region

    async def _find_offer(self, vast: VastAIClient, gpu_names: List[str], price_max: Optional[float], region: Optional[str]) -> Optional[Dict]:
        base_q: Dict = {"rentable": {"eq": True}, "verified": {"eq": True}}
        if price_max is not None:
            base_q["dph_total"] = {"lte": price_max}
        offers = await vast.search_offers(base_q)
        # Region filter fix
        offers = [o for o in offers if is_in_region(str(o.get("geolocation", "")), region)]
        for gpu in gpu_names:
            needle = gpu.replace("_", " ").lower()
            exact = [o for o in offers if str(o.get("gpu_name", "")).lower() == needle]
            if exact:
                logger.info("offer match (exact)", gpu_name=gpu, count=len(exact))
                return exact[0]
            fuzzy = [o for o in offers if needle in str(o.get("gpu_name", "")).lower()]
            logger.info("offer match (substring)", gpu_name=gpu, count=len(fuzzy))
            if fuzzy:
                return fuzzy[0]
        return None

    # ... rest of file unchanged ...
