#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai (CLI-based)
- Uses vastai CLI for offer search and instance lifecycle
- Structured logging with structlog (JSON)
- Backoff/rate-limit + simple circuit breaker
"""
import asyncio
import json
import os
import re
import shutil
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

# 3.11 compatibility shim for libs importing from collections
import collections as _collections
import collections.abc as _abc
for _n in ("Mapping", "MutableMapping", "Sequence", "Callable"):
    if not hasattr(_collections, _n) and hasattr(_abc, _n):
        setattr(_collections, _n, getattr(_abc, _n))

import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

# ---- Logging ----
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# ---- Env/config ----
VAST_API_KEY = os.getenv("VAST_API_KEY")
NODE_NAME = os.getenv("NODE_NAME", "vast-gpu-node-python")
FORCE_GPU_TYPE = os.getenv("FORCE_GPU_TYPE")
FORCE_IMAGE = os.getenv("FORCE_IMAGE")
FORCE_PRICE_MAX = os.getenv("FORCE_PRICE_MAX")

# Safety
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

# ---- Vast CLI client ----
class VastAIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cli_path = self._find_cli()
        self._setup_api_key()

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

# ---- VK core ----
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
        log.info("vk_init", node=node_name, api_key_len=len(api_key))

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

    def _base_node(self) -> k8s_client.V1Node:
        return k8s_client.V1Node(
            metadata=k8s_client.V1ObjectMeta(
                name=self.node_name,
                labels={
                    "beta.kubernetes.io/arch": "amd64",
                    "beta.kubernetes.io/os": "linux",
                    "node.kubernetes.io/instance-type": "gpu",
                    "provider": "vast.ai",
                },
                annotations={"node.alpha.kubernetes.io/ttl": "0"},
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
        node = self._base_node()
        try:
            self.v1.create_node(body=node)
            log.info("node_registered", node=self.node_name)
        except ApiException as e:
            if e.status == 409:
                log.info("node_exists", node=self.node_name)
            else:
                log.error("node_register_fail", error=str(e))
                raise

    async def update_node_status(self):
        try:
            node = self.v1.read_node(name=self.node_name)
            if node.status and node.status.conditions:
                for c in node.status.conditions:
                    c.last_heartbeat_time = self._now()
                    if c.type == "Ready":
                        c.status = "True"
                        c.reason = "KubeletReady"
                        c.message = "kubelet is posting ready status"
            self.v1.replace_node_status(name=self.node_name, body=node)
            log.debug("node_status_updated", node=self.node_name)
        except ApiException as e:
            log.error("node_status_fail", error=str(e))

    async def update_node_lease(self):
        lease_name = self.node_name
        ns = "kube-node-lease"
        try:
            try:
                lease = self.coordination.read_namespaced_lease(name=lease_name, namespace=ns)
                lease.spec.renew_time = self._now()
                lease.spec.holder_identity = self.node_name
                self.coordination.replace_namespaced_lease(name=lease_name, namespace=ns, body=lease)
            except ApiException as e:
                if e.status == 404:
                    lease = k8s_client.V1Lease(
                        metadata=k8s_client.V1ObjectMeta(name=lease_name, namespace=ns),
                        spec=k8s_client.V1LeaseSpec(holder_identity=self.node_name, lease_duration_seconds=40, renew_time=self._now()),
                    )
                    self.coordination.create_namespaced_lease(namespace=ns, body=lease)
                else:
                    raise
            log.debug("node_lease_updated", node=self.node_name)
        except ApiException as e:
            log.error("node_lease_fail", error=str(e))

    async def heartbeat_loop(self):
        while True:
            try:
                await self.update_node_status()
                await self.update_node_lease()
                await asyncio.sleep(10)
            except Exception as e:
                log.error("heartbeat_error", error=str(e))
                await asyncio.sleep(10)

    async def reconcile_existing_pods(self):
        try:
            pods = self.v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={self.node_name}").items
            for pod in pods:
                if self._is_target_pod(pod):
                    name = pod.metadata.name
                    if name not in self.pod_instances and (not pod.status or pod.status.phase in (None, "Pending")):
                        log.info("reconcile_pod", pod=name)
                        try:
                            await self.create_pod(pod)
                            self.consecutive_failures = 0
                        except Exception:
                            self.consecutive_failures += 1
                            if self.consecutive_failures >= CIRCUIT_FAILS_TO_OPEN:
                                self.circuit_open_until = time.time() + CIRCUIT_OPEN_SEC
                                log.warning("circuit_open", seconds=CIRCUIT_OPEN_SEC)
                            raise
        except Exception as e:
            log.error("reconcile_error", error=str(e))

    async def pod_watch_loop(self):
        w = k8s_watch.Watch()
        while True:
            try:
                if time.time() < self.circuit_open_until:
                    rem = int(self.circuit_open_until - time.time())
                    log.info("circuit_wait", seconds=rem)
                    await asyncio.sleep(5)
                    continue
                stream = w.stream(self.v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", timeout_seconds=60)
                for ev in stream:
                    typ = ev.get("type")
                    pod = ev.get("object")
                    if not pod:
                        continue
                    name = pod.metadata.name
                    if typ == "ADDED":
                        if self._is_target_pod(pod) and name not in self.pod_instances:
                            log.info("pod_added", pod=name)
                            try:
                                await self.create_pod(pod)
                                self.consecutive_failures = 0
                            except Exception:
                                self.consecutive_failures += 1
                                if self.consecutive_failures >= CIRCUIT_FAILS_TO_OPEN:
                                    self.circuit_open_until = time.time() + CIRCUIT_OPEN_SEC
                                    log.warning("circuit_open", seconds=CIRCUIT_OPEN_SEC)
                                raise
                    elif typ == "MODIFIED":
                        if pod.metadata.deletion_timestamp or (pod.status and pod.status.phase in ("Succeeded", "Failed")):
                            if name in self.pod_instances:
                                log.info("pod_modified_delete", pod=name)
                                await self.delete_pod(pod)
                    elif typ == "DELETED":
                        if name in self.pod_instances:
                            log.info("pod_deleted", pod=name)
                            await self.delete_pod(pod)
            except Exception as e:
                log.error("watch_error", error=str(e))
                await asyncio.sleep(3)

    def _parse_ann(self, pod) -> tuple:
        ann = pod.metadata.annotations or {}
        gpu_primary = FORCE_GPU_TYPE or ann.get("vast.ai/gpu-type", "RTX 4060")
        fall = ann.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary] + ([g.strip() for g in fall.split(",")] if fall else [])
        price_max = float(FORCE_PRICE_MAX or ann.get("vast.ai/price-max", "0.50"))
        region = ann.get("vast.ai/region")
        return gpu_list, price_max, region, ann

    async def _find_offer(self, vast: 'VastAIClient', gpu_list: List[str], price_max: float, region: Optional[str]) -> Optional[Dict[str, Any]]:
        for g in (gpu_list[:3] if len(gpu_list) > 3 else gpu_list):
            log.info("search_offers", gpu=g)
            offers = await vast.search_offers(g, price_max, region)
            if offers:
                offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                best = offers_sorted[0]
                log.info("offer_match", gpu=g, offer=best.get("id"), price=best.get("dph_total"))
                return best
        log.warning("no_offers", tried=gpu_list[:3] if len(gpu_list) > 3 else gpu_list)
        return None

    async def create_pod(self, pod):
        name = pod.metadata.name
        log.info("create_pod", pod=name)
        try:
            gpu_list, price_max, region, ann = self._parse_ann(pod)
            async with VastAIClient(self.api_key) as vast:  # context kept for symmetry
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_failed(pod, "No GPU instances available via CLI")
                    return
                async with INSTANCE_BUY_SEMAPHORE:
                    res = await vast.buy_instance(offer["id"], ann)
                if not res:
                    await self.update_pod_failed(pod, "Failed to create instance via CLI")
                    return
                iid = res.get("new_contract")
                try:
                    iid_int = int(iid)
                except Exception:
                    await self.update_pod_failed(pod, f"Invalid instance ID: {iid}")
                    return
                ready = await vast.poll_ready(iid_int, timeout=900)
                if not ready:
                    await vast.destroy(iid_int)
                    await self.update_pod_failed(pod, "Instance failed to start via CLI")
                    return
                instance = {
                    "id": iid_int,
                    "status": "running",
                    "public_ip": ready.get("public_ipaddr"),
                    "ssh_port": ready.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready,
                }
                self.pod_instances[name] = instance
                await self.update_pod_running(pod, instance)
                log.info("pod_created", pod=name, iid=iid_int)
        except Exception as e:
            log.error("create_pod_error", pod=name, error=str(e))
            await self.update_pod_failed(pod, str(e))

    async def update_pod_failed(self, pod, reason: str):
        try:
            pod.status.phase = "Failed"
            pod.status.reason = reason
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            log.info("pod_failed", pod=pod.metadata.name, reason=reason)
        except Exception as e:
            log.error("pod_status_fail", error=str(e))

    async def update_pod_running(self, pod, inst):
        try:
            pod.status.phase = "Running"
            pod.status.pod_ip = inst.get("public_ip")
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
            log.info("pod_running", pod=pod.metadata.name, iid=inst.get("id"))
        except Exception as e:
            log.error("pod_status_fail", error=str(e))

    async def delete_pod(self, pod):
        name = pod.metadata.name
        inst = self.pod_instances.get(name)
        if not inst:
            log.warning("inst_missing", pod=name)
            return
        try:
            async with VastAIClient(self.api_key) as vast:
                await vast.destroy(inst["id"]) 
            del self.pod_instances[name]
            log.info("pod_deleted", pod=name, iid=inst["id"]) 
        except Exception as e:
            log.error("delete_pod_error", pod=name, error=str(e))

# ---- HTTP ----
async def healthz(request):
    return web.Response(text="ok")

async def readyz(request):
    return web.json_response({"status": "ready"})

async def build_app(vk: VirtualKubelet) -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", readyz)
    return app

# ---- Main ----
async def main():
    if not VAST_API_KEY:
        log.error("missing_api_key")
        await asyncio.sleep(60)
        return
    vk = VirtualKubelet(VAST_API_KEY, NODE_NAME)
    await vk.register_node()
    app = await build_app(vk)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10255)
    await site.start()
    log.info("vk_started", node=NODE_NAME)

    heartbeat = asyncio.create_task(vk.heartbeat_loop())
    reconcile = asyncio.create_task(vk.reconcile_existing_pods())
    watch = asyncio.create_task(vk.pod_watch_loop())

    try:
        await asyncio.gather(heartbeat, reconcile, watch)
    except Exception as e:
        log.error("vk_main_error", error=str(e))
        # keep process alive for logs
        while True:
            await asyncio.sleep(60)
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
