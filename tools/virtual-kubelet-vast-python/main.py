#!/usr/bin/env python3
"""
Enhanced Virtual Kubelet Provider for Vast.ai - robust error handling, throttled polling, single-flight per pod, auto-heal on external deletion, and reduced log spam.
"""
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

import aiohttp
import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_konfig, watch as k8s_watch
from kubernetes.client.rest import ApiException

try:
    import asyncssh
    SSH_AVAILABLE = True
except Exception:
    SSH_AVAILABLE = False

structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])
logger = structlog.get_logger()

VAST_API_KEY = os.getenv("VAST_API_KEY")
NODE_NAME = os.getenv("NODE_NAME", "vast-gpu-node-python")
FORCE_GPU_TYPE = os.getenv("FORCE_GPU_TYPE")
FORCE_IMAGE = os.getenv("FORCE_IMAGE")
FORCE_PRICE_MAX = os.getenv("FORCE_PRICE_MAX")

from asyncio import Semaphore
INSTANCE_BUY_SEMAPHORE = Semaphore(1)
GLOBAL_RPS = 0.5
BACKOFF_INITIAL = 5.0
BACKOFF_MAX = 60.0
CIRCUIT_FAILS_TO_OPEN = 5
CIRCUIT_OPEN_SEC = 300.0
SHOW_POLL_INTERVAL_MIN = 15
SHOW_POLL_INTERVAL_JITTER = 4
INSTANCE_RECREATE_GRACE = 120

_last_call_ts = 0.0
async def _respect_global_rate_limit():
    global _last_call_ts
    min_interval = 1.0 / max(GLOBAL_RPS, 0.1)
    now = time.time()
    sleep_for = (_last_call_ts + min_interval) - now
    if sleep_for > 0:
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
                return p
        return None
    def _setup_api_key(self):
        if self.api_key:
            fpath = os.path.expanduser("~/.vastai_api_key")
            with open(fpath, "w") as f:
                f.write(self.api_key)
            os.chmod(fpath, 0o600)
    async def _run(self, args: List[str]) -> Dict[str, Any]:
        if not self.cli_path:
            return {"error": "vastai CLI not available"}
        await _respect_global_rate_limit()
        proc = await asyncio.create_subprocess_exec(*([self.cli_path] + args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        out, err = await proc.communicate()
        if proc.returncode != 0:
            em = (err.decode() or "").strip()
            # Vast bug: NoneType error on show__instance means transient failure
            if "show__instance" in em and "start_date" in em:
                return {"transient_error": True}
            # Vast returns 404/not found instance - treat as external delete
            if "not found" in em.lower() or "does not exist" in em.lower():
                return {"gone": True}
            return {"error": em, "returncode": proc.returncode}
        txt = (out.decode() or "").strip()
        try:
            return {"data": json.loads(txt)} if txt and txt[0] in "[{" else {"data": txt}
        except Exception:
            return {"data": txt}
    async def search_offers(self, gpu_type: str, max_price: float, region: Optional[str]) -> List[Dict[str, Any]]:
        gpu_cli = gpu_type.replace(" ", "_")
        parts = ["rentable=true","verified=true","rented=false",f"gpu_name={gpu_cli}",f"dph<={max_price:.2f}","reliability>=0.70","inet_down>=50","inet_up>=20"]
        if region:
            r = region.strip().lower()
            if r in ("north america","na"): parts.append("geolocation in [US,CA,MX]")
            elif r in ("us","usa","united states"): parts.append("geolocation=US")
            elif r in ("canada","ca"): parts.append("geolocation=CA")
            elif r in ("europe","eu"): parts.append("geolocation in [DE,FR,GB,IT,ES]")
            elif "=" in region: parts.append(region)
        res = await self._run(["search","offers","--raw","--no-default"," ".join(parts),"-o","dph+"])
        if "error" in res: return []
        data = res.get("data", [])
        return data if isinstance(data, list) else []
    async def buy_instance(self, ask_id: int, ann: Dict[str,str]) -> Optional[Dict[str, Any]]:
        image = FORCE_IMAGE or ann.get("vast.ai/image", "ozzuworld/june-multi-gpu:latest")
        disk_str = ann.get("vast.ai/disk", "50")
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except Exception:
            disk_gb = 50.0
        args = ["create","instance",str(ask_id),"--raw","--image",image,"--disk",str(int(disk_gb))]
        if "vast.ai/onstart-cmd" in ann: args += ["--onstart-cmd", ann["vast.ai/onstart-cmd"]]
        if "vast.ai/env" in ann: args += ["--env", ann["vast.ai/env"]]
        res = await self._run(args)
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            return {"new_contract": int(data)}
        if isinstance(data, dict) and "new_contract" in data:
            return data
        return None
    async def poll_instance_ready(self, instance_id: int, timeout_seconds: int = 600, poll_min=SHOW_POLL_INTERVAL_MIN) -> Optional[Dict[str, Any]]:
        start = time.time()
        last_log = start
        while time.time() - start < timeout_seconds:
            res = await self._run(["show","instance",str(instance_id),"--raw"])
            if "gone" in res:
                return {"gone": True}
            if "transient_error" in res:
                await asyncio.sleep(poll_min)
                continue
            data = res.get("data")
            if isinstance(data, dict) and data.get("actual_status") == "running" and data.get("ssh_host"):
                return data
            # Log sparsely
            now = time.time()
            if now - last_log > 30:
                logger.debug("Instance not ready yet (poll)", instance_id=instance_id)
                last_log = now
            await asyncio.sleep(poll_min + int(time.time()) % SHOW_POLL_INTERVAL_JITTER)
        return None
    async def delete_instance(self, instance_id: int) -> bool:
        res = await self._run(["destroy","instance",str(instance_id)])
        return "error" not in res

class VirtualKubelet:
    def __init__(self, api_key: str, node_name: str):
        self.api_key = api_key
        self.node_name = node_name
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        self.pod_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0
        self.recreate_backoff: Dict[str, float] = defaultdict(float)  # pod_name -> next_allowed_recreate_time
        try:
            k8s_konfig.load_incluster_config()
        except Exception:
            k8s_konfig.load_kube_config()
        self.v1 = k8s_client.CoreV1Api()
        self.coordination = k8s_client.CoordinationV1Api()
        logger.info("VK init", node=node_name, ssh_available=SSH_AVAILABLE)
    def _now(self):
        return datetime.now(timezone.utc)
    def _is_target_pod(self, pod) -> bool:
        try:
            return pod and pod.spec and pod.spec.node_name == self.node_name and (pod.metadata.deletion_timestamp is None)
        except Exception:
            return False
    async def create_pod(self, pod):
        pod_name = pod.metadata.name
        async with self.pod_locks[pod_name]:
            instance = self.pod_instances.get(pod_name)
            if instance and instance.get("state") in ("provisioning","running"):
                logger.info("pod already has instance", pod=pod_name, instance_id=instance.get("id"))
                return
            now = time.time()
            if now < self.recreate_backoff[pod_name]:
                logger.debug("Delaying recreate due to backoff", pod=pod_name, delay=int(self.recreate_backoff[pod_name]-now))
                return
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_status_failed(pod, "No GPU offers available"); return
                async with INSTANCE_BUY_SEMAPHORE:
                    buy = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})
                if not buy or not buy.get("new_contract"):
                    await self.update_pod_status_failed(pod, "Failed to create instance"); return
                iid = int(buy["new_contract"])
                self.pod_instances[pod_name] = {
                    "id": iid, "state": "provisioning", "created": time.time(),
                    "offer": offer, "ssh_poll_at": 0, "gone_poll_count": 0, "poll_fail_count": 0
                }
                logger.info("Instance created", pod=pod_name, iid=iid)
                ready = await vast.poll_instance_ready(iid)
                if ready and not ready.get("gone"):
                    self.pod_instances[pod_name].update({"state": "running", "instance_data": ready, "gone_poll_count": 0, "poll_fail_count": 0})
                    await self.update_pod_status_running(pod, self.pod_instances[pod_name])
                elif ready and ready.get("gone"):
                    self.pod_instances.pop(pod_name, None)
                    self.recreate_backoff[pod_name] = time.time() + INSTANCE_RECREATE_GRACE
                    await self.update_pod_status_failed(pod, "External deletion - will retry")
                else:
                    self.pod_instances.pop(pod_name, None)
                    self.recreate_backoff[pod_name] = time.time() + INSTANCE_RECREATE_GRACE
                    await self.update_pod_status_failed(pod, "Provisioning failed")
    async def update_pod_status_failed(self, pod, reason: str):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            pod.status.phase = "Failed"; pod.status.reason = reason
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
        except Exception: pass
    async def update_pod_status_running(self, pod, instance):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            pod.status.phase = "Running"; pod.status.pod_ip = instance.get("instance_data",{}).get("public_ip")
            if not pod.status.conditions: pod.status.conditions = []
            for t in ("PodScheduled","Initialized","ContainersReady","Ready"):
                pod.status.conditions.append(k8s_client.V1PodCondition(type=t, status="False" if t in ("ContainersReady","Ready") else "True", last_transition_time=self._now(), reason="Scheduled" if t=="PodScheduled" else ("PodCompleted" if t=="Initialized" else "ContainersNotReady")))
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
        except Exception: pass
    async def delete_pod(self, pod):
        pod_name = pod.metadata.name
        async with self.pod_locks[pod_name]:
            instance = self.pod_instances.get(pod_name)
            if not instance: return
            try:
                async with VastAIClient(self.api_key) as vast:
                    await vast.delete_instance(instance["id"])
                self.pod_instances.pop(pod_name, None)
                self.recreate_backoff[pod_name] = 0
            except Exception: pass
    def _parse_annotations(self, pod) -> tuple:
        ann = pod.metadata.annotations or {}
        gpu_primary = FORCE_GPU_TYPE or ann.get("vast.ai/gpu-type", "RTX 4060")
        gpu_fallbacks = ann.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary] + ([g.strip() for g in gpu_fallbacks.split(",")] if gpu_fallbacks else [])
        price_max = float(FORCE_PRICE_MAX or ann.get("vast.ai/price-max", "0.50"))
        region = ann.get("vast.ai/region")
        return gpu_list, price_max, region
    async def _find_offer(self, vast: 'VastAIClient', gpu_list: List[str], price_max: float, region: Optional[str]) -> Optional[Dict[str, Any]]:
        for gpu in (gpu_list[:3] if len(gpu_list) > 3 else gpu_list):
            offers = await vast.search_offers(gpu, price_max, region)
            if offers:
                offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                return offers_sorted[0]
        return None
    async def reconcile_existing_pods(self):
        try:
            pods = self.v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={self.node_name}").items
            for pod in pods:
                if self._is_target_pod(pod):
                    await self.create_pod(pod)
        except Exception as e:
            logger.error("reconcile_existing_pods error", err=str(e))
    async def pod_watch_loop(self):
        w = k8s_watch.Watch()
        while True:
            try:
                now = time.time()
                if now < self.circuit_open_until:
                    await asyncio.sleep(5); continue
                stream = w.stream(self.v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", timeout_seconds=60)
                for event in stream:
                    typ = event.get("type"); pod = event.get("object")
                    if not pod: continue
                    name = pod.metadata.name
                    logger.debug("Pod event", typ=typ, pod=name)
                    if typ == "ADDED":
                        await self.create_pod(pod)
                    elif typ == "MODIFIED":
                        if pod.metadata.deletion_timestamp or (pod.status and pod.status.phase in ("Succeeded","Failed")):
                            await self.delete_pod(pod)
                    elif typ == "DELETED":
                        await self.delete_pod(pod)
            except Exception as e:
                logger.error("pod_watch_loop error", err=str(e))
                await asyncio.sleep(3)
    async def heartbeat_loop(self):
        while True:
            try:
                pods = list(self.pod_instances.keys())
                for pod_name in pods:
                    await self._poll_and_healthcheck_instance(pod_name)
                await asyncio.sleep(10)
            except Exception as e:
                logger.error("Heartbeat error", err=str(e))
                await asyncio.sleep(10)
    async def _poll_and_healthcheck_instance(self, pod_name):
        instance = self.pod_instances.get(pod_name)
        if not instance: return
        iid = instance.get("id")
        now = time.time()
        # Rate limit show polling
        if now < instance.get("ssh_poll_at", 0): return
        instance["ssh_poll_at"] = now + SHOW_POLL_INTERVAL_MIN + int(now) % SHOW_POLL_INTERVAL_JITTER
        gone_count = instance.get("gone_poll_count", 0)
        fail_count = instance.get("poll_fail_count", 0)
        try:
            async with VastAIClient(self.api_key) as vast:
                show = await vast._run(["show","instance",str(iid),"--raw"])
                if "gone" in show:
                    gone_count += 1
                elif "transient_error" in show:
                    return
                else:
                    gone_count = 0
                data = show.get("data")
                if data and data.get("actual_status") == "running" and data.get("ssh_host"):
                    health = await self._check_instance_health(data)
                else:
                    health = False
                # If many gone polls in a row, treat as externally deleted
                if gone_count > 1:
                    logger.info("Instance deleted externally; cleaning up", pod=pod_name, iid=iid)
                    self.pod_instances.pop(pod_name, None)
                    self.recreate_backoff[pod_name] = time.time() + INSTANCE_RECREATE_GRACE
                    return
                # If failed health checks > X, mark not ready
                if not health:
                    fail_count += 1
                else:
                    fail_count = 0
                # Update for next round
                instance["gone_poll_count"] = gone_count
                instance["poll_fail_count"] = fail_count
                # Update pod readiness for pod
                pod = self.try_get_pod(pod_name)
                if pod:
                    await self._set_pod_ready(pod, health and gone_count == 0 and fail_count < 3, reason="Healthy" if health else "Unhealthy")
        except Exception as e:
            logger.error("Poll/health check failed", pod=pod_name, err=str(e))
    async def _check_instance_health(self, data: dict) -> bool:
        if not SSH_AVAILABLE:
            return False
        ssh_host = data.get("ssh_host"); ssh_port = data.get("ssh_port", 22)
        if not ssh_host:
            return False
        try:
            async with asyncssh.connect(ssh_host, port=ssh_port, username="root", known_hosts=None, connect_timeout=10) as conn:
                res = await conn.run("curl -f -m 5 http://localhost:8000/healthz && curl -f -m 5 http://localhost:8001/healthz", check=False)
                return res.exit_status == 0
        except Exception:
            return False
    def try_get_pod(self, pod_name):
        try:
            return self.v1.read_namespaced_pod(name=pod_name, namespace="june-services")
        except Exception:
            return None
    async def _set_pod_ready(self, pod, ready: bool, reason: str):
        if not pod.status:
            pod.status = k8s_client.V1PodStatus()
        pod.status.phase = "Running"
        if not pod.status.conditions:
            pod.status.conditions = []
        def _get(cond_type):
            for c in pod.status.conditions:
                if c.type == cond_type: return c
            c = k8s_client.V1PodCondition(type=cond_type, status="False", last_transition_time=self._now())
            pod.status.conditions.append(c)
            return c
        c_ready = _get("Ready"); c_cont = _get("ContainersReady")
        for c in (c_ready, c_cont):
            c.status = "True" if ready else "False"
            c.reason = reason
            c.last_transition_time = self._now()
        try:
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
        except Exception:
            pass

# Minimal endpoints (health + log proxy)
async def healthz(request):
    return web.Response(text="ok")
async def readyz(request):
    return web.json_response({"status":"ready","ssh":SSH_AVAILABLE})

async def build_app(vk: VirtualKubelet) -> web.Application:
    app = web.Application()
    app.router.add_get('/healthz', healthz)
    app.router.add_get('/readyz', readyz)
    async def logs_handler(request):
        pod = request.query.get('pod');
        inst = vk.pod_instances.get(pod or "") if pod else None
        if not inst:
            return web.Response(text="pod not found", status=404)
        if not SSH_AVAILABLE:
            return web.Response(text="ssh unavailable", status=501)
        ssh_host = inst.get("instance_data",{}).get("ssh_host"); ssh_port = inst.get("instance_data",{}).get("ssh_port",22)
        try:
            async with asyncssh.connect(ssh_host, port=ssh_port, username="root", known_hosts=None) as conn:
                res = await conn.run("tail -n 200 /var/log/supervisor/supervisord.log 2>/dev/null || true; tail -n 100 /var/log/supervisor/tts.log 2>/dev/null || true; tail -n 100 /var/log/supervisor/stt.log 2>/dev/null || true", check=False)
                return web.Response(text=res.stdout or "")
        except Exception as e:
            return web.Response(text=str(e), status=500)
    app.router.add_get('/logs', logs_handler)
    return app

async def main():
    if not VAST_API_KEY:
        logger.error("VAST_API_KEY required"); return
    vk = VirtualKubelet(VAST_API_KEY, NODE_NAME)
    await vk.register_node()
    app = await build_app(vk)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10255); await site.start()
    hb = asyncio.create_task(vk.heartbeat_loop())
    rec = asyncio.create_task(vk.reconcile_existing_pods())
    watch = asyncio.create_task(vk.pod_watch_loop())
    try:
        await asyncio.gather(hb, rec, watch)
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
