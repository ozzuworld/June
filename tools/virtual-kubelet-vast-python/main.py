#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai
- Simple pod management for GPU instances  
- Single instance limit for development
- Uses VAST_API_KEY from environment
"""
# Python 3.10+ compatibility shim for libraries importing collections.Callable
try:
    from collections.abc import Callable as _VKCallable
    import collections as _VKCollections
    if not hasattr(_VKCollections, "Callable"):
        _VKCollections.Callable = _VKCallable
except Exception:
    # Best-effort; safe no-op if not needed
    pass

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from collections import defaultdict
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import structlog
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

try:
    import asyncssh
    SSH_AVAILABLE = True
except Exception:
    SSH_AVAILABLE = False

structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])
logger = structlog.get_logger()

class VastAIClient:
    BASE_URL = "https://console.vast.ai/api/v0"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cli_path = self._find_cli_path()

    def _find_cli_path(self) -> Optional[str]:
        paths = [shutil.which("vastai"), "/usr/local/bin/vastai", "/app/vastai"]
        for p in paths:
            if p and os.path.exists(p) and os.access(p, os.X_OK):
                return p
        return None

    async def _http_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Direct REST call to Vast.ai API with aiohttp."""
        import aiohttp
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.BASE_URL}{path}"
        timeout = aiohttp.ClientTimeout(total=20)
        # Use default SSL verification; pod image should provide CA store. Caller may disable via env if needed.
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, params=params, ssl=None if os.getenv("VAST_DISABLE_SSL_VERIFY") == "1" else True) as resp:
                txt = await resp.text()
                if resp.status != 200:
                    logger.error("Vast API GET failed", status=resp.status, path=path, body=txt)
                    return {"error": f"HTTP {resp.status}", "body": txt}
                try:
                    return {"data": await resp.json()}
                except Exception:
                    return {"data": txt}

    async def search_offers(self, gpu_type: str, max_price: float, region: Optional[str]) -> List[Dict[str, Any]]:
        """Use Vast.ai REST API to search offers instead of the CLI to avoid TLS issues inside container."""
        # Map inputs to API params
        gpu_cli = gpu_type.replace(" ", "_")
        params = {
            "verified": "true",
            "rentable": "true",
            "rented": "false",
            "gpu_name": gpu_cli,
            # price filters
            "dph_lte": f"{max_price:.2f}",
            # optional quality filters similar to CLI defaults
            "reliability_gte": "0.70",
            "inet_down_gte": "50",
            "inet_up_gte": "20",
            # sort cheapest first if supported
            "order": "dph+"
        }
        if region:
            r = region.strip().lower()
            if r in ("north america", "na"):
                params["geolocation_in"] = "US,CA,MX"
            elif r in ("us", "usa", "united states"):
                params["geolocation"] = "US"
            elif r in ("canada", "ca"):
                params["geolocation"] = "CA"
            elif r in ("europe", "eu"):
                params["geolocation_in"] = "DE,FR,GB,IT,ES"

        logger.info("Searching offers (REST)", gpu_type=gpu_type, max_price=max_price, region=region, params=params)
        res = await self._http_get("/bundles", params)
        if "error" in res:
            logger.error("REST search offers failed", error=res["error"])
            return []
        data = res.get("data") or {}
        # API returns either a list or {offers:[...]}
        offers = data.get("offers") if isinstance(data, dict) else data
        offers = offers or []
        logger.info("Found offers", count=len(offers))
        return offers

    async def buy_instance(self, ask_id: int, ann: Dict[str,str]) -> Optional[Dict[str, Any]]:
        image = ann.get("vast.ai/image", "ozzuworld/june-multi-gpu:latest")
        disk_str = ann.get("vast.ai/disk", "50")
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except Exception:
            disk_gb = 50.0
        # Keep CLI for create for now (can be migrated to REST later)
        if not self.cli_path:
            logger.error("vastai CLI not available for create instance")
            return None
        args = ["create", "instance", str(ask_id), "--raw", "--image", image, "--disk", str(int(disk_gb))]
        if "vast.ai/onstart-cmd" in ann:
            args += ["--onstart-cmd", ann["vast.ai/onstart-cmd"]]
        env_parts = ["-p 8000:8000 -p 8001:8001"]
        if "vast.ai/env" in ann:
            env_parts.append(ann["vast.ai/env"])
        env_string = " ".join(env_parts)
        args += ["--env", env_string]
        logger.info("Creating Vast.ai instance", image=image, env=env_string, ask_id=ask_id)
        # Reuse CLI runner for create
        res = await self._run_cli(args)
        if "error" in res:
            logger.error("Failed to create instance", error=res["error"]) 
            return None
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            return {"new_contract": int(data)}
        if isinstance(data, dict) and "new_contract" in data:
            return data
        return None

    async def _run_cli(self, args: List[str]) -> Dict[str, Any]:
        """Dedicated CLI runner with relaxed TLS env if needed."""
        if not self.cli_path:
            return {"error": "vastai CLI not available"}
        try:
            env = os.environ.copy()
            env.setdefault("PYTHONHTTPSVERIFY", "0")
            env.setdefault("CURL_CA_BUNDLE", "")
            env.setdefault("REQUESTS_CA_BUNDLE", "")
            proc = await asyncio.create_subprocess_exec(
                *([self.cli_path] + args),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                em = (err.decode() or "").strip()
                return {"error": em}
            txt = (out.decode() or "").strip()
            try:
                return {"data": json.loads(txt)} if txt and txt[0] in "[{" else {"data": txt}
            except Exception:
                return {"data": txt}
        except Exception as e:
            return {"error": str(e)}

    async def show_instance(self, instance_id: int) -> Dict[str, Any]:
        # Keep CLI for now
        return await self._run_cli(["show", "instance", str(instance_id), "--raw"])

    async def destroy_instance(self, instance_id: int) -> Dict[str, Any]:
        # Keep CLI for now
        return await self._run_cli(["destroy", "instance", str(instance_id)])

class VirtualKubelet:
    def __init__(self):
        self.api_key = os.getenv("VAST_API_KEY")
        self.node_name = os.getenv("NODE_NAME", "vast-gpu-node-python")
        self.max_instances = int(os.getenv("MAX_INSTANCES", "1"))
        if not self.api_key:
            raise ValueError("VAST_API_KEY environment variable is required")
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        self.instance_keys: Dict[str, str] = {}  # desired_key -> pod_name
        self.recreate_backoff: Dict[str, float] = defaultdict(float)
        self.vast_client = VastAIClient(self.api_key)
        try:
            k8s_konfig.load_incluster_config()
        except Exception:
            k8s_konfig.load_kube_config()
        self.v1 = k8s_client.CoreV1Api()
        logger.info("VirtualKubelet initialized", node=self.node_name, max_instances=self.max_instances, ssh_available=SSH_AVAILABLE)

    def _now(self):
        return datetime.now(timezone.utc)

    def _is_target_pod(self, pod) -> bool:
        try:
            return (pod and pod.spec and pod.spec.node_name == self.node_name and pod.metadata.deletion_timestamp is None)
        except Exception:
            return False

    def get_desired_key(self, pod):
        if pod.metadata.owner_references:
            return pod.metadata.owner_references[0].uid
        return pod.metadata.uid

    async def create_pod(self, pod):
        pod_name = pod.metadata.name
        desired_key = self.get_desired_key(pod)
        now = time.time()
        logger.info("Creating pod", pod=pod_name, desired_key=desired_key)
        if len(self.pod_instances) >= self.max_instances:
            logger.info("Instance cap reached, not provisioning", current=len(self.pod_instances), max=self.max_instances)
            await self.update_pod_status_failed(pod, "Instance limit reached")
            return
        if (self.instance_keys.get(desired_key) and self.pod_instances.get(self.instance_keys[desired_key])):
            logger.info("Instance already tracked", key=desired_key)
            return
        if now < self.recreate_backoff[pod_name]:
            delay = int(self.recreate_backoff[pod_name] - now)
            logger.debug("Delaying recreation due to backoff", pod=pod_name, delay=delay)
            return
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            offer = await self._find_offer(gpu_list, price_max, region)
            if not offer:
                await self.update_pod_status_failed(pod, "No GPU offers available")
                return
            buy_result = await self.vast_client.buy_instance(offer["id"], pod.metadata.annotations or {})
            if not buy_result or not buy_result.get("new_contract"):
                await self.update_pod_status_failed(pod, "Failed to create instance")
                return
            instance_id = int(buy_result["new_contract"])
            self.pod_instances[pod_name] = {"id": instance_id, "state": "provisioning", "created": time.time(), "offer": offer}
            self.instance_keys[desired_key] = pod_name
            logger.info("Instance created, waiting for ready state", pod=pod_name, instance_id=instance_id)
            await self._wait_for_instance_ready(pod, pod_name, desired_key, instance_id)
        except Exception as e:
            logger.error("Pod creation failed with exception", pod=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, f"Creation error: {e}")

    async def _wait_for_instance_ready(self, pod, pod_name: str, desired_key: str, instance_id: int):
        start_time = time.time(); timeout = 600
        while time.time() - start_time < timeout:
            try:
                show_result = await self.vast_client.show_instance(instance_id)
                if show_result.get("gone"):
                    logger.info("Instance deleted externally, scheduling recreate", pod=pod_name)
                    self.pod_instances.pop(pod_name, None); self.instance_keys.pop(desired_key, None)
                    self.recreate_backoff[pod_name] = time.time() + 120
                    await self.update_pod_status_failed(pod, "External deletion - will retry"); return
                data = show_result.get("data")
                if isinstance(data, dict):
                    status = data.get("actual_status"); ssh_host = data.get("ssh_host")
                    if status == "running" and ssh_host:
                        self.pod_instances[pod_name].update({"state": "running", "instance_data": data})
                        await self.update_pod_status_running(pod, self.pod_instances[pod_name]); return
                    elif status in ("exited", "stopped"):
                        await self.update_pod_status_failed(pod, f"Instance failed with status: {status}"); return
                await asyncio.sleep(15)
            except Exception as e:
                logger.error("Error during instance wait", pod=pod_name, error=str(e)); await asyncio.sleep(30)
        await self.update_pod_status_failed(pod, "Provisioning timeout")

    async def update_pod_status_failed(self, pod, reason: str):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            pod.status.phase = "Failed"; pod.status.reason = reason; pod.status.message = f"Vast.ai provider: {reason}"
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            logger.info("Updated pod status to Failed", pod=pod.metadata.name, reason=reason)
        except Exception as e:
            logger.error("Failed to update pod status", pod=pod.metadata.name, error=str(e))

    async def update_pod_status_running(self, pod, instance):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            instance_data = instance.get("instance_data", {})
            pod.status.phase = "Running"; pod.status.pod_ip = instance_data.get("public_ip"); pod.status.host_ip = instance_data.get("ssh_host"); pod.status.start_time = self._now()
            conditions = [("PodScheduled","True","Scheduled","Pod has been scheduled"),("Initialized","True","PodCompleted","Init containers completed"),("Ready","True","PodReady","Pod is ready"),("ContainersReady","True","ContainersReady","Containers are ready")]
            pod.status.conditions = []
            for condition_type, status, reason, message in conditions:
                pod.status.conditions.append(k8s_client.V1PodCondition(type=condition_type, status=status, last_transition_time=self._now(), reason=reason, message=message))
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            logger.info("Updated pod status to Running", pod=pod.metadata.name, pod_ip=pod.status.pod_ip)
        except Exception as e:
            logger.error("Failed to update pod status", pod=pod.metadata.name, error=str(e))

    async def delete_pod(self, pod):
        pod_name = pod.metadata.name; desired_key = self.get_desired_key(pod)
        logger.info("Deleting pod", pod=pod_name)
        instance = self.pod_instances.get(pod_name)
        if instance:
            try:
                await self.vast_client.destroy_instance(instance["id"])
                logger.info("Destroyed Vast.ai instance", pod=pod_name, instance_id=instance["id"]) 
            except Exception as e:
                logger.error("Failed to destroy instance", pod=pod_name, error=str(e))
        self.pod_instances.pop(pod_name, None); self.instance_keys.pop(desired_key, None); self.recreate_backoff[pod_name] = 0

    def _parse_annotations(self, pod) -> tuple:
        ann = pod.metadata.annotations or {}
        gpu_primary = ann.get("vast.ai/gpu-type", "RTX 3060"); gpu_fallbacks = ann.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary] + ([g.strip() for g in gpu_fallbacks.split(",")] if gpu_fallbacks else [])
        price_max = float(ann.get("vast.ai/price-max", "0.50")); region = ann.get("vast.ai/region", "US")
        return gpu_list, price_max, region

    async def _find_offer(self, gpu_list: List[str], price_max: float, region: Optional[str]) -> Optional[Dict[str, Any]]:
        for gpu in gpu_list[:3]:
            try:
                offers = await self.vast_client.search_offers(gpu, price_max, region)
                if offers:
                    offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                    return offers_sorted[0]
            except Exception as e:
                logger.warning("Failed to search offers", gpu=gpu, error=str(e)); continue
        return None

    async def register_node(self):
        try:
            try:
                node = self.v1.read_node(name=self.node_name); logger.info("Node already exists", node=self.node_name); return
            except ApiException as e:
                if e.status != 404:
                    logger.error("Error checking node", error=str(e)); return
            node = k8s_client.V1Node(
                metadata=k8s_client.V1ObjectMeta(name=self.node_name, labels={"beta.kubernetes.io/arch":"amd64","beta.kubernetes.io/os":"linux","kubernetes.io/arch":"amd64","kubernetes.io/os":"linux","kubernetes.io/role":"agent","type":"virtual-kubelet","vast.ai/gpu-node":"true"}),
                spec=k8s_client.V1NodeSpec(taints=[k8s_client.V1Taint(key="virtual-kubelet.io/provider", value="vast-ai", effect="NoSchedule"), k8s_client.V1Taint(key="vast.ai/gpu-only", value="true", effect="NoExecute")]),
                status=k8s_client.V1NodeStatus(addresses=[k8s_client.V1NodeAddress(type="InternalIP", address="127.0.0.1")], allocatable={"cpu":"8","memory":"32Gi","nvidia.com/gpu":"1","ephemeral-storage":"100Gi","pods":str(self.max_instances)}, capacity={"cpu":"8","memory":"32Gi","nvidia.com/gpu":"1","ephemeral-storage":"100Gi","pods":str(self.max_instances)}, conditions=[k8s_client.V1NodeCondition(type="Ready", status="True", last_heartbeat_time=self._now(), last_transition_time=self._now(), reason="VirtualKubeletReady", message="Virtual Kubelet is ready")], node_info=k8s_client.V1NodeSystemInfo(machine_id="virtual-kubelet-vast", system_uuid="virtual-kubelet-vast", boot_id="virtual-kubelet-vast", kernel_version="5.4.0", os_image="Ubuntu 22.04", container_runtime_version="vastai://1.0.0", kubelet_version="v1.28.0", kube_proxy_version="v1.28.0", operating_system="linux", architecture="amd64"))
            )
            self.v1.create_node(body=node); logger.info("Node registered successfully", node=self.node_name)
        except Exception as e:
            logger.error("Failed to register node", node=self.node_name, error=str(e))

    async def pod_watch_loop(self):
        w = k8s_watch.Watch()
        while True:
            try:
                logger.info("Starting pod watch", node=self.node_name)
                stream = w.stream(self.v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", timeout_seconds=60)
                for event in stream:
                    event_type = event.get("type"); pod = event.get("object")
                    if not pod: continue
                    pod_name = pod.metadata.name
                    if event_type == "ADDED":
                        await self.create_pod(pod)
                    elif event_type == "MODIFIED":
                        if (pod.metadata.deletion_timestamp or (pod.status and pod.status.phase in ("Succeeded", "Failed"))):
                            await self.delete_pod(pod)
                    elif event_type == "DELETED":
                        await self.delete_pod(pod)
            except Exception as e:
                logger.error("Pod watch error", error=str(e)); await asyncio.sleep(5)

    async def heartbeat_loop(self):
        while True:
            try:
                try:
                    node = self.v1.read_node(name=self.node_name)
                    if node.status and node.status.conditions:
                        for condition in node.status.conditions:
                            if condition.type == "Ready":
                                condition.last_heartbeat_time = self._now()
                    self.v1.patch_node_status(name=self.node_name, body=node)
                    logger.debug("Heartbeat sent", node=self.node_name)
                except Exception as e:
                    logger.error("Heartbeat failed", error=str(e))
                await asyncio.sleep(30)
            except Exception:
                logger.error("Heartbeat loop error", error=str(e)); await asyncio.sleep(15)

async def main():
    try:
        vk = VirtualKubelet()
        await vk.register_node()
        logger.info("Virtual Kubelet started", node=vk.node_name, max_instances=vk.max_instances)
        tasks = [asyncio.create_task(vk.heartbeat_loop(), name="heartbeat"), asyncio.create_task(vk.pod_watch_loop(), name="pod_watch")]
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error("Fatal error", error=str(e)); raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested"); exit(0)
