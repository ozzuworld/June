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
        return gpu_name.replace(" ", "_")
    
    def _build_search_query(self, gpu_type: str, max_price: float, region: Optional[str] = None) -> str:
        gpu_cli = self._gpu_name_to_cli_format(gpu_type)
        query_parts = [
            "rentable=True",
            "verified=True",
            "rented=False",
            f"gpu_name={gpu_cli}",
            f"dph <= {max_price}",
            "reliability >= 0.90",
            "inet_down >= 100",
        ]
        if region:
            region_map = {"US": "geolocation=US", "Europe": "geolocation=DE", "Asia": "geolocation=JP"}
            query_parts.append(region_map.get(region, region))
        return " ".join(query_parts)
    
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
        result = await self._run_cli_command(["search", "offers", "--raw", "--no-default", query, "-o", "dph-"])
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
        image = pod_annotations.get("vast.ai/image", "pytorch/pytorch:2.2.0-cuda12.1-cudnn8-devel")
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
    
    async def poll_instance_ready(self, instance_id: int, timeout_seconds: int = 300) -> Optional[Dict[str, Any]]:
        start = time.time()
        while (time.time() - start) < timeout_seconds:
            res = await self._run_cli_command(["show", "instance", str(instance_id), "--raw"])
            if "error" in res:
                logger.warning("Error polling instance via CLI", instance_id=instance_id, error=res["error"])
                await asyncio.sleep(10)
                continue
            data = res.get("data")
            if isinstance(data, dict):
                status = data.get("actual_status")
                if status == "running" and data.get("ssh_host"):
                    logger.info("Instance ready via CLI", instance_id=instance_id, ssh_host=data.get("ssh_host"))
                    return data
                logger.debug("Instance not ready yet via CLI", instance_id=instance_id, status=status)
            await asyncio.sleep(10)
        logger.error("Instance readiness timeout via CLI", instance_id=instance_id, timeout_seconds=timeout_seconds)
        return None
    
    async def delete_instance(self, instance_id: int) -> bool:
        res = await self._run_cli_command(["destroy", "instance", str(instance_id)])
        if "error" in res:
            e = res["error"].lower()
            if "not found" in e or "does not exist" in e:
                logger.info("Instance already deleted via CLI", instance_id=instance_id)
                return True
            logger.error("Failed to delete instance via CLI", instance_id=instance_id, error=res["error"])
            return False
        logger.info("Instance deleted via CLI", instance_id=instance_id)
        return True


class VirtualKubelet:
    def __init__(self, api_key: str, node_name: str):
        self.api_key = api_key
        self.node_name = node_name
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0
        try:
            k8s_konfig.load_incluster_config()
        except Exception:
            k8s_konfig.load_kube_config()
        self.v1 = k8s_client.CoreV1Api()
        self.coordination = k8s_client.CoordinationV1Api()
        logger.info("VirtualKubelet initialized", node_name=node_name, api_key_length=len(api_key))

    def _now(self):
        return datetime.now(timezone.utc)

    def _is_target_pod(self, pod) -> bool:
        try:
            return (
                pod is not None and
                pod.spec is not None and
                pod.spec.node_name == self.node_name and
                (pod.metadata.deletion_timestamp is None)
            )
        except Exception:
            return False

    def _base_node_object(self) -> k8s_client.V1Node:
        return k8s_client.V1Node(
            metadata=k8s_client.V1ObjectMeta(
                name=self.node_name,
                labels={
                    "beta.kubernetes.io/arch": "amd64",
                    "beta.kubernetes.io/os": "linux",
                    "node.kubernetes.io/instance-type": "gpu",
                    "provider": "vast.ai",
                },
                annotations={"node.alpha.kubernetes.io/ttl": "0"}
            ),
            spec=k8s_client.V1NodeSpec(
                taints=[
                    k8s_client.V1Taint(key="vast.ai/gpu", effect="NoSchedule"),
                    k8s_client.V1Taint(key="virtual-kubelet.io/provider", value="vast", effect="NoSchedule"),
                ]
            ),
            status=k8s_client.V1NodeStatus(
                capacity={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                allocatable={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                addresses=[k8s_client.V1NodeAddress(type="InternalIP", address="10.0.0.1")],
                node_info=k8s_client.V1NodeSystemInfo(
                    machine_id="vk-machine-id",
                    system_uuid="vk-system-uuid",
                    boot_id=f"vk-{int(time.time())}",
                    kernel_version="5.15.0",
                    os_image="Ubuntu 22.04 LTS",
                    operating_system="linux",
                    architecture="amd64",
                    container_runtime_version="docker://24.0.0",
                    kubelet_version="v1.28.0-vk-vast-python-cli",
                    kube_proxy_version="v1.28.0-vk-vast-python-cli",
                ),
                conditions=[
                    k8s_client.V1NodeCondition(type="Ready", status="True", last_heartbeat_time=self._now(), last_transition_time=self._now(), reason="KubeletReady", message="kubelet is posting ready status"),
                    k8s_client.V1NodeCondition(type="MemoryPressure", status="False", last_heartbeat_time=self._now(), last_transition_time=self._now(), reason="KubeletHasSufficientMemory", message="kubelet has sufficient memory available"),
                    k8s_client.V1NodeCondition(type="DiskPressure", status="False", last_heartbeat_time=self._now(), last_transition_time=self._now(), reason="KubeletHasNoDiskPressure", message="kubelet has no disk pressure"),
                    k8s_client.V1NodeCondition(type="PIDPressure", status="False", last_heartbeat_time=self._now(), last_transition_time=self._now(), reason="KubeletHasSufficientPID", message="kubelet has sufficient PID available"),
                ],
            ),
        )

    async def register_node(self):
        node = self._base_node_object()
        try:
            self.v1.create_node(body=node)
            logger.info("Node registered successfully", node_name=self.node_name)
        except ApiException as e:
            if e.status == 409:
                logger.info("Node already exists", node_name=self.node_name)
            else:
                logger.error("Failed to register node", error=str(e))
                raise

    async def update_node_status(self):
        try:
            node = self.v1.read_node(name=self.node_name)
            if node.status and node.status.conditions:
                for cond in node.status.conditions:
                    cond.last_heartbeat_time = self._now()
                    if cond.type == "Ready":
                        cond.status = "True"
                        cond.reason = "KubeletReady"
                        cond.message = "kubelet is posting ready status"
            self.v1.replace_node_status(name=self.node_name, body=node)
            logger.debug("Node status updated", node_name=self.node_name)
        except ApiException as e:
            logger.error("Failed to update node status", error=str(e))

    async def update_node_lease(self):
        lease_name = self.node_name
        namespace = "kube-node-lease"
        try:
            try:
                lease = self.coordination.read_namespaced_lease(name=lease_name, namespace=namespace)
                lease.spec.renew_time = self._now()
                lease.spec.holder_identity = self.node_name
                self.coordination.replace_namespaced_lease(name=lease_name, namespace=namespace, body=lease)
            except ApiException as e:
                if e.status == 404:
                    lease = k8s_client.V1Lease(
                        metadata=k8s_client.V1ObjectMeta(name=lease_name, namespace=namespace),
                        spec=k8s_client.V1LeaseSpec(holder_identity=self.node_name, lease_duration_seconds=40, renew_time=self._now()),
                    )
                    self.coordination.create_namespaced_lease(namespace=namespace, body=lease)
                else:
                    raise
            logger.debug("Node lease updated", node_name=self.node_name)
        except ApiException as e:
            logger.error("Failed to update node lease", error=str(e))

    async def heartbeat_loop(self):
        while True:
            try:
                await self.update_node_status()
                await self.update_node_lease()
                await asyncio.sleep(10)
            except Exception as e:
                logger.error("Heartbeat loop error", error=str(e))
                await asyncio.sleep(10)

    async def reconcile_existing_pods(self):
        try:
            pods = self.v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={self.node_name}").items
            for pod in pods:
                if self._is_target_pod(pod):
                    name = pod.metadata.name
                    if name not in self.pod_instances and (not pod.status or pod.status.phase in (None, "Pending")):
                        logger.info("Reconciling pod", pod_name=name)
                        try:
                            await self.create_pod(pod)
                            self.consecutive_failures = 0
                        except Exception:
                            self.consecutive_failures += 1
                            if self.consecutive_failures >= CIRCUIT_FAILS_TO_OPEN:
                                self.circuit_open_until = time.time() + CIRCUIT_OPEN_SEC
                                logger.warning("Circuit opened due to failures", open_seconds=CIRCUIT_OPEN_SEC)
                            raise
        except Exception as e:
            logger.error("reconcile_existing_pods error", error=str(e))

    async def pod_watch_loop(self):
        w = k8s_watch.Watch()
        while True:
            try:
                now = time.time()
                if now < self.circuit_open_until:
                    logger.info("Circuit breaker is open, pausing pod processing", remaining_seconds=int(self.circuit_open_until - now))
                    await asyncio.sleep(5)
                    continue
                stream = w.stream(self.v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", timeout_seconds=60)
                for event in stream:
                    typ = event.get("type")
                    pod = event.get("object")
                    if not pod:
                        continue
                    name = pod.metadata.name
                    if typ == "ADDED":
                        if self._is_target_pod(pod) and name not in self.pod_instances:
                            logger.info("Pod event ADDED", pod_name=name)
                            try:
                                await self.create_pod(pod)
                                self.consecutive_failures = 0
                            except Exception:
                                self.consecutive_failures += 1
                                if self.consecutive_failures >= CIRCUIT_FAILS_TO_OPEN:
                                    self.circuit_open_until = time.time() + CIRCUIT_OPEN_SEC
                                    logger.warning("Circuit opened due to failures", open_seconds=CIRCUIT_OPEN_SEC)
                                raise
                    elif typ == "MODIFIED":
                        if pod.metadata.deletion_timestamp or (pod.status and pod.status.phase in ("Succeeded", "Failed")):
                            if name in self.pod_instances:
                                logger.info("Pod event MODIFIED->delete", pod_name=name)
                                await self.delete_pod(pod)
                    elif typ == "DELETED":
                        if name in self.pod_instances:
                            logger.info("Pod event DELETED", pod_name=name)
                            await self.delete_pod(pod)
            except Exception as e:
                logger.error("pod_watch_loop error", error=str(e))
                await asyncio.sleep(3)

    def _parse_annotations(self, pod) -> tuple:
        annotations = pod.metadata.annotations or {}
        gpu_primary = annotations.get("vast.ai/gpu-type", "RTX 4060")
        gpu_fallbacks = annotations.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary]
        if gpu_fallbacks:
            gpu_list.extend([g.strip() for g in gpu_fallbacks.split(",")])
        price_max = float(annotations.get("vast.ai/price-max", "0.50"))
        region = annotations.get("vast.ai/region")
        return gpu_list, price_max, region

    async def _find_offer(self, vast: 'VastAIClient', gpu_list: List[str], price_max: float, region: Optional[str]) -> Optional[Dict[str, Any]]:
        limited_gpu_list = gpu_list[:2] if len(gpu_list) > 2 else gpu_list
        for gpu_type in limited_gpu_list:
            logger.info("Searching offers via CLI", gpu_type=gpu_type)
            offers = await vast.search_offers(gpu_type=gpu_type, max_price=price_max, region=region)
            if offers:
                offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                best_offer = offers_sorted[0]
                logger.info("Offer match found via CLI", gpu_type=gpu_type, offer_id=best_offer.get("id"), price=best_offer.get("dph_total"))
                return best_offer
        logger.warning("No offers found via CLI", gpu_list=limited_gpu_list)
        return None

    async def create_pod(self, pod):
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai via CLI", pod_name=pod_name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_status_failed(pod, "No GPU instances available via CLI")
                    return
                async with INSTANCE_BUY_SEMAPHORE:
                    buy_result = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})
                if not buy_result:
                    await self.update_pod_status_failed(pod, "Failed to create instance via CLI")
                    return
                instance_id = buy_result.get("new_contract")
                if not instance_id:
                    await self.update_pod_status_failed(pod, "Invalid instance ID in CLI response")
                    return
                try:
                    instance_id_int = int(instance_id)
                except (ValueError, TypeError):
                    await self.update_pod_status_failed(pod, f"Invalid instance ID format from CLI: {instance_id}")
                    return
                ready_instance = await vast.poll_instance_ready(instance_id_int, timeout_seconds=300)
                if not ready_instance:
                    await vast.delete_instance(instance_id_int)
                    await self.update_pod_status_failed(pod, "Instance failed to start via CLI")
                    return
                instance = {
                    "id": instance_id_int,
                    "status": "running",
                    "public_ip": ready_instance.get("public_ipaddr"),
                    "ssh_port": ready_instance.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready_instance
                }
                self.pod_instances[pod_name] = instance
                await self.update_pod_status_running(pod, instance)
                logger.info("Pod created successfully via CLI", pod_name=pod_name, instance_id=instance_id_int)
        except Exception as e:
            logger.error("Error creating pod via CLI", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))

    async def update_pod_status_failed(self, pod, reason: str):
        try:
            pod.status.phase = "Failed"
            pod.status.reason = reason
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            logger.info("Pod marked as failed", pod_name=pod.metadata.name, reason=reason)
        except Exception as e:
            logger.error("Failed to update pod status", error=str(e))

    async def update_pod_status_running(self, pod, instance):
        try:
            pod.status.phase = "Running"
            pod.status.pod_ip = instance.get("public_ip")
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            logger.info("Pod marked as running", pod_name=pod.metadata.name, instance_id=instance.get("id"))
        except Exception as e:
            logger.error("Failed to update pod status", error=str(e))

    async def delete_pod(self, pod):
        pod_name = pod.metadata.name
        instance = self.pod_instances.get(pod_name)
        if not instance:
            logger.warning("Instance not found", pod_name=pod_name)
            return
        try:
            async with VastAIClient(self.api_key) as vast:
                await vast.delete_instance(instance["id"])
            del self.pod_instances[pod_name]
            logger.info("Pod deleted via CLI", pod_name=pod_name, instance_id=instance["id"])
        except Exception as e:
            logger.error("Error deleting pod via CLI", pod_name=pod_name, error=str(e))

# HTTP server for health checks
async def healthz(request):
    return web.Response(text="ok")

async def readyz(request):
    return web.json_response({"status": "ready"})

async def build_app(vk: VirtualKubelet) -> web.Application:
    app = web.Application()
    app.router.add_get('/healthz', healthz)
    app.router.add_get('/readyz', readyz)
    return app

async def main():
    if not VAST_API_KEY:
        logger.error("VAST_API_KEY environment variable required")
        return
    vk = VirtualKubelet(VAST_API_KEY, NODE_NAME)
    await vk.register_node()
    app = await build_app(vk)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10255)
    await site.start()
    logger.info("Virtual Kubelet started with CLI integration", node_name=NODE_NAME)
    heartbeat_task = asyncio.create_task(vk.heartbeat_loop())
    reconcile_task = asyncio.create_task(vk.reconcile_existing_pods())
    watch_task = asyncio.create_task(vk.pod_watch_loop())
    try:
        await asyncio.gather(heartbeat_task, watch_task)
    except asyncio.CancelledError:
        logger.info("Tasks cancelled")
    except KeyboardInterrupt:
        logger.info("Shutting down")
        for t in (heartbeat_task, watch_task, reconcile_task):
            t.cancel()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
