#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai (robust, with GONE detection)
- Single global instance cap
- Idempotency keyed per ReplicaSet UID
- Handles Vast GUI deletions: detects 'gone' and recreates after cooldown
- No async context manager usage
- Uses Tailscale userspace networking (no privileged containers needed)
- Launches separate STT/TTS prebuilt images on the Vast instance via docker compose
"""
import asyncio
import base64
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
FORCE_IMAGE = os.getenv("FORCE_IMAGE")  # optional: starting image (base) on Vast
FORCE_PRICE_MAX = os.getenv("FORCE_PRICE_MAX")
MAX_ACTIVE_INSTANCES = 1

from asyncio import Semaphore
INSTANCE_BUY_SEMAPHORE = Semaphore(1)
SHOW_POLL_INTERVAL_MIN = 15
SHOW_POLL_INTERVAL_JITTER = 4
INSTANCE_RECREATE_GRACE = 120

# Compose + onstart templates used to bring up june-tts and june-stt on Vast instance
COMPOSE_YAML = r"""
version: "3.9"
services:
  june-tts:
    image: ghcr.io/ozzuworld/june-tts:latest
    container_name: june-tts
    restart: unless-stopped
    environment:
      - TTS_PORT=${TTS_PORT:-8000}
      - TTS_HOME=/app/models
      - NUMBA_DISABLE_JIT=1
      - NUMBA_CACHE_DIR=/tmp/numba_cache
      - PYTORCH_JIT=0
      - OMP_NUM_THREADS=1
      - TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY}
    volumes:
      - tts-models:/app/models
      - tts-cache:/app/cache
    ports:
      - "${TTS_PORT:-8000}:8000"

  june-stt:
    image: ghcr.io/ozzuworld/june-stt:latest
    container_name: june-stt
    restart: unless-stopped
    environment:
      - STT_PORT=${STT_PORT:-8001}
      - WHISPER_DEVICE=cuda
      - WHISPER_COMPUTE_TYPE=float16
      - NUMBA_DISABLE_JIT=1
      - NUMBA_CACHE_DIR=/tmp/numba_cache
      - TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY}
    volumes:
      - stt-models:/app/models
      - stt-cache:/app/cache
    ports:
      - "${STT_PORT:-8001}:8001"

volumes:
  tts-models: {}
  tts-cache: {}
  stt-models: {}
  stt-cache: {}
"""

BASH_ONSTART = r"""
set -euo pipefail

# Ensure docker-compose or docker compose is available
if ! docker compose version >/dev/null 2>&1; then
  if ! command -v docker-compose >/dev/null 2>&1; then
    echo "[INIT] Installing docker-compose..."
    curl -L "https://github.com/docker/compose/releases/download/2.27.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
  fi
end

# Write compose file
mkdir -p /root/june
cat > /root/june/june-stack.yml <<'EOF'
{compose}
EOF

# Prepare .env with values provided by provider
cat > /root/june/.env <<EOF
TAILSCALE_AUTH_KEY={tailscale_auth}
TTS_PORT={tts_port}
STT_PORT={stt_port}
EOF

# Bring up the stack
cd /root/june
if docker compose version >/dev/null 2>&1; then
  docker compose --env-file .env -f june-stack.yml up -d
else
  docker-compose --env-file .env -f june-stack.yml up -d
fi

# Basic health loop
for i in $(seq 1 40); do
  if curl -sf http://localhost:${{TTS_PORT:-8000}}/healthz >/dev/null 2>&1 && \
     curl -sf http://localhost:${{STT_PORT:-8001}}/healthz >/dev/null 2>&1; then
    echo "[INIT] Both services healthy"; exit 0
  fi
  echo "[INIT] Waiting for services... ($i/40)"; sleep 6
done

echo "[INIT] Services not healthy within timeout"; exit 1
"""

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
        proc = await asyncio.create_subprocess_exec(
            *([self.cli_path] + args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            em = (err.decode() or "").strip()
            lowered = em.lower()
            if "not found" in lowered or "does not exist" in lowered or "404" in lowered:
                return {"gone": True}
            if "show__instance" in em and "start_date" in em:
                return {"transient_error": True}
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
        # IMPORTANT: Pass query tokens separately, not as one string
        query_parts = " ".join(parts).split()
        res = await self._run(["search","offers","--raw"] + query_parts + ["-o","dph+"])
        if "error" in res: return []
        data = res.get("data", [])
        return data if isinstance(data, list) else []

    def _build_tailscale_env_string(self, pod) -> str:
        """Build Tailscale environment variables from pod env or secrets"""
        env_vars = []
        if pod.spec and pod.spec.containers:
            for container in pod.spec.containers:
                if container.env:
                    for env_var in container.env:
                        if env_var.name.startswith('TAILSCALE_'):
                            if env_var.value:
                                env_vars.append(f"-e {env_var.name}={env_var.value}")
                            elif env_var.value_from and env_var.value_from.secret_key_ref:
                                try:
                                    secret = self.v1.read_namespaced_secret(
                                        name=env_var.value_from.secret_key_ref.name,
                                        namespace=pod.metadata.namespace
                                    )
                                    if secret.data and env_var.value_from.secret_key_ref.key in secret.data:
                                        import base64
                                        value = base64.b64decode(secret.data[env_var.value_from.secret_key_ref.key]).decode()
                                        env_vars.append(f"-e {env_var.name}={value}")
                                except Exception as e:
                                    logger.warning("Failed to get secret value", env_var=env_var.name, error=str(e))
        return " ".join(env_vars)

    async def buy_instance(self, ask_id: int, ann: Dict[str,str], pod) -> Optional[Dict[str, Any]]:
        # Starting/base image for Vast instance
        image = os.getenv("VAST_START_IMAGE") or FORCE_IMAGE or ann.get("vast.ai/start-image", "ubuntu:22.04")
        disk_str = ann.get("vast.ai/disk", "50")
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except Exception:
            disk_gb = 50.0

        # Ports (configurable via annotations)
        tts_port = ann.get("june.tts/port", "8000")
        stt_port = ann.get("june.stt/port", "8001")

        # Extract TAILSCALE_AUTH_KEY from Pod env if present
        tailscale_env = self._build_tailscale_env_string(pod)
        tailscale_key = ""
        if tailscale_env:
            m = re.search(r"-e TAILSCALE_AUTH_KEY=([^\s]+)", tailscale_env)
            if m:
                tailscale_key = m.group(1)

        # Render onstart script with embedded compose
        onstart_script = BASH_ONSTART.format(
            compose=COMPOSE_YAML,
            tailscale_auth=tailscale_key,
            tts_port=tts_port,
            stt_port=stt_port,
        )

        args = [
            "create","instance",str(ask_id),"--raw",
            "--image", image,
            "--disk", str(int(disk_gb)),
            "--onstart-cmd", onstart_script,
        ]

        logger.info("Creating Vast.ai instance with compose-based runtime",
                    image=image, tts_port=tts_port, stt_port=stt_port)

        res = await self._run(args)
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            return {"new_contract": int(data)}
        if isinstance(data, dict) and "new_contract" in data:
            return data
        return None

    async def show_instance(self, instance_id: int) -> Dict[str, Any]:
        return await self._run(["show","instance",str(instance_id),"--raw"])

class VirtualKubelet:
    def __init__(self, api_key: str, node_name: str):
        self.api_key = api_key
        self.node_name = node_name
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        self.instance_keys: Dict[str, str] = {}
        self.recreate_backoff: Dict[str, float] = defaultdict(float)
        try:
            k8s_konfig.load_incluster_config()
        except Exception:
            k8s_konfig.load_kube_config()
        self.v1 = k8s_client.CoreV1Api()
        logger.info("VK init with userspace networking", node=node_name, ssh_available=SSH_AVAILABLE)

    def _now(self):
        return datetime.now(timezone.utc)

    def _is_target_pod(self, pod) -> bool:
        try:
            return pod and pod.spec and pod.spec.node_name == self.node_name and (pod.metadata.deletion_timestamp is None)
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
        if len(self.pod_instances) >= MAX_ACTIVE_INSTANCES:
            logger.info("Instance cap hit, not provisioning new GPU", cap=MAX_ACTIVE_INSTANCES)
            return
        if self.instance_keys.get(desired_key) and self.pod_instances.get(self.instance_keys[desired_key]):
            logger.info("Instance already tracked for desired_key", key=desired_key)
            return
        if now < self.recreate_backoff[pod_name]:
            logger.debug("Delaying recreate due to backoff", pod=pod_name, delay=int(self.recreate_backoff[pod_name]-now))
            return
        gpu_list, price_max, region = self._parse_annotations(pod)
        vast = VastAIClient(self.api_key)
        vast.v1 = self.v1
        offer = await self._find_offer(vast, gpu_list, price_max, region)
        if not offer:
            await self.update_pod_status_failed(pod, "No GPU offers available"); return
        async with INSTANCE_BUY_SEMAPHORE:
            buy = await vast.buy_instance(offer["id"], pod.metadata.annotations or {}, pod)
        if not buy or not buy.get("new_contract"):
            await self.update_pod_status_failed(pod, "Failed to create instance"); return
        iid = int(buy["new_contract"])
        self.pod_instances[pod_name] = {"id": iid, "state": "provisioning", "created": time.time(), "offer": offer, "gone": False}
        self.instance_keys[desired_key] = pod_name
        logger.info("Instance created with userspace networking", pod=pod_name, iid=iid)

        show = await vast.show_instance(iid)
        if "gone" in show:
            await self._handle_instance_gone(pod, pod_name, desired_key)
            return

        start = time.time()
        while time.time() - start < 600:
            show = await vast.show_instance(iid)
            if "gone" in show:
                await self._handle_instance_gone(pod, pod_name, desired_key)
                return
            if "transient_error" in show:
                await asyncio.sleep(SHOW_POLL_INTERVAL_MIN)
                continue
            data = show.get("data")
            if isinstance(data, dict) and data.get("actual_status") == "running" and data.get("ssh_host"):
                self.pod_instances[pod_name].update({"state": "running", "instance_data": data})
                await self.update_pod_status_running(pod, self.pod_instances[pod_name])
                return
            await asyncio.sleep(SHOW_POLL_INTERVAL_MIN)

        await self._handle_instance_fail(pod, pod_name, desired_key, reason="Provisioning timeout")

    async def _handle_instance_gone(self, pod, pod_name: str, desired_key: str):
        logger.info("Instance deleted externally; scheduling recreate", pod=pod_name)
        self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = time.time() + INSTANCE_RECREATE_GRACE
        await self.update_pod_status_failed(pod, "External deletion - will retry")

    async def _handle_instance_fail(self, pod, pod_name: str, desired_key: str, reason: str):
        logger.warning("Instance provisioning failure", pod=pod_name, reason=reason)
        self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = time.time() + INSTANCE_RECREATE_GRACE
        await self.update_pod_status_failed(pod, reason)

    async def update_pod_status_failed(self, pod, reason: str):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            pod.status.phase = "Failed"; pod.status.reason = reason
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
        except Exception:
            pass

    async def update_pod_status_running(self, pod, instance):
        try:
            if not pod.status: pod.status = k8s_client.V1PodStatus()
            pod.status.phase = "Running"; pod.status.pod_ip = instance.get("instance_data",{}).get("public_ip")
            if not pod.status.conditions: pod.status.conditions = []
            for t in ("PodScheduled","Initialized","ContainersReady","Ready"):
                pod.status.conditions.append(
                    k8s_client.V1PodCondition(
                        type=t,
                        status="False" if t in ("ContainersReady","Ready") else "True",
                        last_transition_time=self._now(),
                        reason="Scheduled" if t=="PodScheduled" else ("PodCompleted" if t=="Initialized" else "ContainersNotReady")
                    )
                )
            self.v1.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=pod)
        except Exception:
            pass

    async def delete_pod(self, pod):
        pod_name = pod.metadata.name
        desired_key = self.get_desired_key(pod)
        instance = self.pod_instances.get(pod_name)
        if not instance: return
        vast = VastAIClient(self.api_key)
        await vast._run(["destroy","instance",str(instance["id")])
        self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = 0

    def _parse_annotations(self, pod) -> tuple:
        ann = pod.metadata.annotations or {}
        gpu_primary = FORCE_GPU_TYPE or ann.get("vast.ai/gpu-type", "RTX 4060")
        gpu_fallbacks = ann.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary] + ([g.strip() for g in gpu_fallbacks.split(",")] if gpu_fallbacks else [])
        price_max = float(FORCE_PRICE_MAX or ann.get("vast.ai/price-max", "0.20"))
        region = ann.get("vast.ai/region", "north america")
        return gpu_list, price_max, region

    async def _find_offer(self, vast: 'VastAIClient', gpu_list: List[str], price_max: float, region: Optional[str]) -> Optional[Dict[str, Any]]:
        for gpu in (gpu_list[:3] if len(gpu_list) > 3 else gpu_list):
            offers = await vast.search_offers(gpu, price_max, region)
            if offers:
                offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                return offers_sorted[0]
        return None

    async def register_node(self):
        try:
            try:
                node = self.v1.read_node(name=self.node_name)
                logger.info("Node already exists", node=self.node_name)
                return
            except ApiException as e:
                if e.status != 404:
                    logger.error("Error checking node", error=str(e))
                    return

            node = k8s_client.V1Node(
                metadata=k8s_client.V1ObjectMeta(
                    name=self.node_name,
                    labels={
                        "beta.kubernetes.io/arch": "amd64",
                        "beta.kubernetes.io/os": "linux",
                        "kubernetes.io/arch": "amd64",
                        "kubernetes.io/os": "linux",
                        "kubernetes.io/role": "agent",
                        "type": "virtual-kubelet",
                        "vast.ai/gpu-node": "true",
                        "vast.ai/networking": "userspace"
                    },
                    annotations={"node.alpha.kubernetes.io/ttl": "0"}
                ),
                spec=k8s_client.V1NodeSpec(
                    taints=[k8s_client.V1Taint(
                        key="virtual-kubelet.io/provider",
                        value="vast-ai",
                        effect="NoSchedule"
                    )]
                ),
                status=k8s_client.V1NodeStatus(
                    addresses=[k8s_client.V1NodeAddress(type="InternalIP", address="127.0.0.1")],
                    allocatable={"cpu": "8","memory": "32Gi","nvidia.com/gpu": "1","ephemeral-storage": "100Gi","pods": "10"},
                    capacity={"cpu": "8","memory": "32Gi","nvidia.com/gpu": "1","ephemeral-storage": "100Gi","pods": "10"},
                    conditions=[k8s_client.V1NodeCondition(
                        type="Ready",
                        status="True",
                        last_heartbeat_time=self._now(),
                        last_transition_time=self._now(),
                        reason="VirtualKubeletReady",
                        message="Virtual Kubelet ready with userspace networking"
                    )],
                    node_info=k8s_client.V1NodeSystemInfo(
                        machine_id="virtual-kubelet-userspace",
                        system_uuid="virtual-kubelet-userspace",
                        boot_id="virtual-kubelet-userspace",
                        kernel_version="5.4.0",
                        os_image="Ubuntu 22.04",
                        container_runtime_version="docker://20.10.0",
                        kubelet_version="v1.28.0",
                        kube_proxy_version="v1.28.0",
                        operating_system="linux",
                        architecture="amd64"
                    )
                )
            )
            self.v1.create_node(body=node)
            logger.info("Node registered successfully with userspace networking", node=self.node_name)
        except Exception as e:
            logger.error("Failed to register node", error=str(e))

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
                # NOTE: your original code had a minor typo list_pod_for_all_namespages
                stream = w.stream(self.v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", timeout_seconds=60)
                for event in stream:
                    typ = event.get("type"); pod = event.get("object")
                    if not pod: continue
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
                await asyncio.sleep(15)
            except Exception as e:
                logger.error("Heartbeat error", err=str(e))
                await asyncio.sleep(10)

# Minimal endpoints
async def healthz(request):
    return web.Response(text="ok")

async def readyz(request):
    return web.json_response({"status":"ready","ssh":SSH_AVAILABLE,"networking":"userspace"})

async def build_app(vk: 'VirtualKubelet') -> web.Application:
    app = web.Application()
    app.router.add_get('/healthz', healthz)
    app.router.add_get('/readyz', readyz)
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
