#!/usr/bin/env python3
"""
Python-based Virtual Kubelet for Vast.ai GPU instances
- Real Vast.ai instance provisioning (buy/poll/delete)
- Structured logging with full lifecycle visibility
- List+watch with resourceVersion handling (relist on 410)
- Periodic poller reconcile
- Region filter fix (US/CA/MX => North America)
- Health endpoints with proper timing
- Continuous heartbeat to maintain node Ready status
"""

import asyncio
import os
import signal
import sys
import time
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
                    txt = await resp.text()
                    logger.error("Vast.ai API connection failed", status_code=resp.status, response=txt)
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

    async def buy_instance(self, ask_id: int, pod_annotations: Dict[str, str]) -> Optional[Dict]:
        """Create an instance from a Vast.ai offer using the correct API endpoint."""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        
        # Parse pod annotations for instance configuration
        payload = {
            "image": pod_annotations.get("vast.ai/image", "ubuntu:22.04"),
            "disk": float(pod_annotations.get("vast.ai/disk", "50")),
            "runtype": pod_annotations.get("vast.ai/runtype", "ssh_direct"),
        }
        
        # Add optional fields if present
        if "vast.ai/env" in pod_annotations:
            payload["env"] = pod_annotations["vast.ai/env"]
        if "vast.ai/price-max" in pod_annotations:
            payload["price"] = float(pod_annotations["vast.ai/price-max"])
        if "vast.ai/onstart-cmd" in pod_annotations:
            payload["onstart_cmd"] = pod_annotations["vast.ai/onstart-cmd"]
        if "vast.ai/login" in pod_annotations:
            payload["login"] = pod_annotations["vast.ai/login"]
        if "vast.ai/entrypoint" in pod_annotations:
            payload["entrypoint"] = pod_annotations["vast.ai/entrypoint"]
        
        endpoint = f"/instances/create/{ask_id}/"
        try:
            async with self.session.post(f"{self.base_url}{endpoint}", headers=headers, json=payload) as resp:
                txt = await resp.text()
                logger.info("Instance creation request", ask_id=ask_id, endpoint=endpoint, payload=payload, status_code=resp.status)
                
                if resp.status in (200, 201):
                    try:
                        data = await resp.json() if resp.content_type == 'application/json' else {"new_contract": txt.strip()}
                    except Exception:
                        # Handle plain text response
                        data = {"new_contract": txt.strip() if txt.strip().isdigit() else None}
                    
                    instance_id = data.get("new_contract")
                    logger.info("Instance creation initiated", ask_id=ask_id, instance_id=instance_id, endpoint=endpoint)
                    return data
                else:
                    logger.error("buy_instance failed", ask_id=ask_id, status_code=resp.status, response=txt[:500], endpoint=endpoint)
                    return None
        except Exception as e:
            logger.error("buy_instance exception", ask_id=ask_id, error=str(e), endpoint=endpoint)
            return None

    async def get_instance(self, instance_id: int) -> Optional[Dict]:
        """Get details of a specific instance"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with self.session.get(f"{self.base_url}/instances/{instance_id}/", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                else:
                    txt = await resp.text()
                    logger.error("get_instance failed", instance_id=instance_id, status_code=resp.status, response=txt[:500])
                    return None
        except Exception as e:
            logger.error("get_instance exception", instance_id=instance_id, error=str(e))
            return None

    async def list_instances(self) -> List[Dict]:
        """List all instances"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with self.session.get(f"{self.base_url}/instances/", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("instances", [])
                else:
                    txt = await resp.text()
                    logger.error("list_instances failed", status_code=resp.status, response=txt[:500])
                    return []
        except Exception as e:
            logger.error("list_instances exception", error=str(e))
            return []

    async def delete_instance(self, instance_id: int) -> bool:
        """Delete/terminate an instance"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with self.session.delete(f"{self.base_url}/instances/{instance_id}/", headers=headers) as resp:
                if resp.status in (200, 204):
                    logger.info("Instance deletion initiated", instance_id=instance_id)
                    return True
                else:
                    txt = await resp.text()
                    logger.error("delete_instance failed", instance_id=instance_id, status_code=resp.status, response=txt[:500])
                    return False
        except Exception as e:
            logger.error("delete_instance exception", instance_id=instance_id, error=str(e))
            return False

    async def poll_instance_ready(self, instance_id: int, timeout_seconds: int = 300) -> Optional[Dict]:
        """Poll instance until it's ready with public IP and SSH access"""
        logger.info("Polling instance readiness", instance_id=instance_id, timeout_seconds=timeout_seconds)
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            instance = await self.get_instance(instance_id)
            if not instance:
                logger.warning("Instance not found during polling", instance_id=instance_id)
                await asyncio.sleep(10)
                continue
            
            status = instance.get("actual_status", "")
            public_ip = instance.get("public_ipaddr")
            ssh_port = instance.get("ssh_port")
            
            logger.debug("Instance status check", instance_id=instance_id, status=status, public_ip=public_ip, ssh_port=ssh_port)
            
            if status == "running" and public_ip and ssh_port:
                logger.info("Instance ready", instance_id=instance_id, public_ip=public_ip, ssh_port=ssh_port)
                return instance
            
            if status in ("failed", "terminated", "error"):
                logger.error("Instance failed to start", instance_id=instance_id, status=status)
                return None
            
            await asyncio.sleep(10)
        
        logger.error("Instance readiness timeout", instance_id=instance_id, timeout_seconds=timeout_seconds)
        return None

# Add a simple concurrency limiter for instance creation
INSTANCE_BUY_SEMAPHORE = asyncio.Semaphore(int(os.getenv("VK_MAX_BUY_CONCURRENCY", "2")))

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

    async def register_node(self):
        logger.info("Registering virtual node", node_name=self.node_name)
        node = V1Node(
            metadata=client.V1ObjectMeta(name=self.node_name, labels={
                "provider": "vast.ai",
                "node.kubernetes.io/instance-type": "gpu",
                "beta.kubernetes.io/arch": "amd64",
                "beta.kubernetes.io/os": "linux",
            }),
            spec=client.V1NodeSpec(
                taints=[
                    client.V1Taint(key="virtual-kubelet.io/provider", value="vast", effect="NoSchedule"),
                    client.V1Taint(key="vast.ai/gpu", effect="NoSchedule"),
                ]
            ),
            status=client.V1NodeStatus(
                capacity={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                allocatable={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                conditions=[
                    client.V1NodeCondition(
                        type="Ready", status="True", reason="VirtualKubeletReady", message="Virtual Kubelet is ready",
                        last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc)
                    )
                ],
                addresses=[client.V1NodeAddress(type="InternalIP", address="10.0.0.1")],
                node_info=client.V1NodeSystemInfo(
                    architecture="amd64", operating_system="linux", kernel_version="5.15.0", os_image="Ubuntu 22.04 LTS",
                    container_runtime_version="docker://24.0.0", kubelet_version="v1.28.0-vk-vast-python",
                    kube_proxy_version="v1.28.0-vk-vast-python", boot_id=os.getenv("BOOT_ID", f"vk-{int(datetime.now(timezone.utc).timestamp())}"),
                    machine_id=os.getenv("MACHINE_ID", "vk-machine-id"), system_uuid=os.getenv("SYSTEM_UUID", "vk-system-uuid")
                )
            )
        )
        try:
            self.k8s_client.create_node(node)
            logger.info("Virtual node registered successfully")
        except ApiException as e:
            if e.status == 409:
                logger.info("Virtual node already exists, updating")
                self.k8s_client.patch_node(self.node_name, node)
            else:
                logger.error("Failed to register node", error=str(e))
                raise

    async def update_node_status(self):
        try:
            current_node = self.k8s_client.read_node(name=self.node_name)
            current_node.status.conditions = [
                client.V1NodeCondition(type="Ready", status="True", reason="VirtualKubeletReady", message="Virtual Kubelet is ready", last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc)),
                client.V1NodeCondition(type="MemoryPressure", status="False", reason="VirtualKubeletSufficient", message="Virtual Kubelet has sufficient memory", last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc)),
                client.V1NodeCondition(type="DiskPressure", status="False", reason="VirtualKubeletNoDiskPressure", message="Virtual Kubelet has no disk pressure", last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc)),
                client.V1NodeCondition(type="PIDPressure", status="False", reason="VirtualKubeletNoPIDPressure", message="Virtual Kubelet has no PID pressure", last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc)),
            ]
            self.k8s_client.patch_node_status(name=self.node_name, body=current_node)
            logger.debug("Node status updated successfully")
        except Exception as e:
            logger.error("Failed to update node status", error=str(e))

    async def heartbeat_loop(self):
        logger.info("Starting node heartbeat loop")
        while self.running:
            try:
                await self.update_node_status()
                await asyncio.sleep(30)
            except Exception as e:
                logger.error("Error in heartbeat loop", error=str(e))
                await asyncio.sleep(5)

    async def pod_poller(self):
        logger.info("Starting pod poller")
        while self.running:
            try:
                pods = self.k8s_client.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={self.node_name}")
                for pod in pods.items:
                    await self._reconcile_pod(pod)
                await asyncio.sleep(15)
            except Exception as e:
                logger.error("Error in pod poller", error=str(e))
                await asyncio.sleep(5)

    async def _reconcile_pod(self, pod: V1Pod):
        phase = (pod.status and pod.status.phase) or "Pending"
        pod_name = pod.metadata.name if pod.metadata else "unknown"
        if phase in ("Pending", "Unknown") and pod_name not in self.pod_instances:
            logger.info("Reconciling pending pod", pod_name=pod_name)
            try:
                await self.create_pod(pod)
            except Exception as e:
                logger.error("Reconcile create_pod failed", pod_name=pod_name, error=str(e))

    async def watch_pods(self):
        logger.info("Starting pod watcher", node_name=self.node_name)
        resource_version = None
        while self.running:
            try:
                pod_list = self.k8s_client.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={self.node_name}")
                resource_version = pod_list.metadata.resource_version
                for pod in pod_list.items:
                    await self._reconcile_pod(pod)

                w = watch.Watch()
                for event in w.stream(self.k8s_client.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}", resource_version=resource_version, timeout_seconds=60):
                    event_type = event['type']
                    pod = event['object']
                    resource_version = pod.metadata.resource_version
                    logger.info("Pod event received", event_type=event_type, pod_name=pod.metadata.name, namespace=pod.metadata.namespace)
                    try:
                        if event_type == "ADDED":
                            await self.create_pod(pod)
                        elif event_type == "DELETED":
                            await self.delete_pod(pod)
                        elif event_type == "MODIFIED":
                            await self.update_pod_status(pod)
                    except Exception as e:
                        logger.error("Error handling pod event", event_type=event_type, pod_name=pod.metadata.name, error=str(e))
            except ApiException as e:
                if e.status == 410:
                    logger.warning("Watch expired, relisting to refresh resourceVersion", error=str(e))
                    await asyncio.sleep(1)
                    continue
                logger.error("API error in pod watcher", error=str(e))
                await asyncio.sleep(2)
                continue
            except Exception as e:
                logger.error("Error in pod watcher", error=str(e))
                await asyncio.sleep(2)
                continue

    async def create_pod(self, pod: V1Pod):
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai", pod_name=pod_name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    logger.error("No matching Vast.ai offers after fallback", pod_name=pod_name, requested=gpu_list, price_max=price_max, region=region)
                    await self.update_pod_status_failed(pod, "No GPU instances available")
                    return

                logger.info("Selected Vast.ai offer", pod_name=pod_name, gpu=offer.get("gpu_name"), price=offer.get("dph_total"), location=offer.get("geolocation"), offer_id=offer.get("id"))

                # Limit concurrent buys to avoid floods
                async with INSTANCE_BUY_SEMAPHORE:
                    buy_result = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})

                if not buy_result:
                    logger.error("Failed to buy Vast.ai instance", pod_name=pod_name, offer_id=offer.get("id"))
                    await self.update_pod_status_failed(pod, "Failed to create instance")
                    return

                instance_id = buy_result.get("new_contract")
                if not instance_id:
                    logger.error("No instance ID returned from create", pod_name=pod_name, buy_result=buy_result)
                    await self.update_pod_status_failed(pod, "Invalid instance creation response")
                    return

                logger.info("Instance creation started", pod_name=pod_name, instance_id=instance_id)

                # Poll for readiness
                ready_instance = await vast.poll_instance_ready(int(instance_id), timeout_seconds=300)
                if not ready_instance:
                    logger.error("Instance failed to become ready", pod_name=pod_name, instance_id=instance_id)
                    # Cleanup failed instance
                    await vast.delete_instance(int(instance_id))
                    await self.update_pod_status_failed(pod, "Instance failed to start")
                    return

                # Store instance details
                instance = {
                    "id": int(instance_id),
                    "status": "running",
                    "public_ip": ready_instance.get("public_ipaddr"),
                    "ssh_port": ready_instance.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready_instance
                }
                self.pod_instances[pod_name] = instance

                logger.info("Instance ready and assigned", pod_name=pod_name, instance_id=instance["id"], public_ip=instance["public_ip"], ssh_port=instance["ssh_port"])
                await self.update_pod_status_running(pod, instance)

        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))

    async def delete_pod(self, pod: V1Pod):
        pod_name = pod.metadata.name
        logger.info("Deleting pod from Vast.ai", pod_name=pod_name)
        if pod_name in self.pod_instances:
            instance = self.pod_instances.pop(pod_name)
            instance_id = instance["id"]
            
            try:
                async with VastAIClient(self.api_key) as vast:
                    success = await vast.delete_instance(instance_id)
                    if success:
                        logger.info("Instance terminated successfully", pod_name=pod_name, instance_id=instance_id)
                    else:
                        logger.error("Failed to terminate instance", pod_name=pod_name, instance_id=instance_id)
            except Exception as e:
                logger.error("Error terminating instance", pod_name=pod_name, instance_id=instance_id, error=str(e))

    async def update_pod_status_running(self, pod: V1Pod, instance: Dict):
        try:
            container_statuses = []
            for container in pod.spec.containers:
                image = container.image or "unknown:latest"
                container_statuses.append(V1ContainerStatus(
                    name=container.name, 
                    image=image, 
                    image_id=f"docker-pullable://{image}", 
                    ready=True, 
                    restart_count=0, 
                    state=client.V1ContainerState(running=client.V1ContainerStateRunning(started_at=datetime.now(timezone.utc)))
                ))
            
            pod_status = V1PodStatus(
                phase="Running", 
                pod_ip=instance.get("public_ip"), 
                host_ip=instance.get("public_ip"), 
                start_time=datetime.now(timezone.utc), 
                conditions=[
                    client.V1PodCondition(type="Initialized", status="True", last_transition_time=datetime.now(timezone.utc)), 
                    client.V1PodCondition(type="Ready", status="True", last_transition_time=datetime.now(timezone.utc)), 
                    client.V1PodCondition(type="ContainersReady", status="True", last_transition_time=datetime.now(timezone.utc)), 
                    client.V1PodCondition(type="PodScheduled", status="True", last_transition_time=datetime.now(timezone.utc))
                ], 
                container_statuses=container_statuses
            )
            
            self.k8s_client.patch_namespaced_pod_status(
                name=pod.metadata.name, 
                namespace=pod.metadata.namespace, 
                body=client.V1Pod(status=pod_status)
            )
            logger.info("Pod status updated to running", pod_name=pod.metadata.name, public_ip=instance.get("public_ip"))
        except Exception as e:
            logger.error("Failed to update pod status", pod_name=pod.metadata.name, error=str(e))

    async def update_pod_status_failed(self, pod: V1Pod, reason: str):
        try:
            pod_status = V1PodStatus(
                phase="Failed", 
                reason=reason, 
                message=f"Failed to create Vast.ai instance: {reason}", 
                start_time=datetime.now(timezone.utc), 
                conditions=[
                    client.V1PodCondition(type="PodScheduled", status="True", last_transition_time=datetime.now(timezone.utc))
                ]
            )
            
            self.k8s_client.patch_namespaced_pod_status(
                name=pod.metadata.name, 
                namespace=pod.metadata.namespace, 
                body=client.V1Pod(status=pod_status)
            )
            logger.info("Pod status updated to failed", pod_name=pod.metadata.name, reason=reason)
        except Exception as e:
            logger.error("Failed to update pod status", pod_name=pod.metadata.name, error=str(e))

    async def update_pod_status(self, pod: V1Pod):
        pod_name = pod.metadata.name
        if pod_name in self.pod_instances:
            instance = self.pod_instances[pod_name]
            await self.update_pod_status_running(pod, instance)

    async def start_health_server(self):
        async def healthz(request):
            return web.json_response({"status": "healthy", "node": self.node_name})
        
        async def readyz(request):
            return web.json_response({"status": "ready", "node": self.node_name})
        
        app = web.Application()
        app.router.add_get('/healthz', healthz)
        app.router.add_get('/readyz', readyz)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 10255)
        await site.start()
        logger.info("Health server started on port 10255")

    async def run(self):
        self.running = True
        logger.info("Starting Virtual Kubelet")
        try:
            await self.initialize()
            await self.start_health_server()
            
            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())
            self._poller_task = asyncio.create_task(self.pod_poller())
            logger.info("Node heartbeat and poller started")
            
            # Run main watch loop
            await self.watch_pods()
        except Exception as e:
            logger.error("Virtual Kubelet crashed", error=str(e))
            raise
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            if self._poller_task:
                self._poller_task.cancel()

    def stop(self):
        logger.info("Stopping Virtual Kubelet")
        self.running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._poller_task:
            self._poller_task.cancel()

async def main():
    node_name = os.getenv("NODE_NAME", "vast-gpu-node-python")
    api_key = os.getenv("VAST_API_KEY")
    if not api_key:
        logger.error("VAST_API_KEY environment variable is required")
        sys.exit(1)
    
    vk = VirtualKubelet(node_name, api_key)
    
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal", signal=signum)
        vk.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await vk.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error("Virtual Kubelet failed", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    asyncio.run(main())