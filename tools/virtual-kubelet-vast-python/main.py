#!/usr/bin/env python3
"""
Python-based Virtual Kubelet for Vast.ai GPU instances
Provides better debugging and error visibility than Go version
"""

import asyncio
import json
import logging
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


class VastAIClient:
    """Client for Vast.ai API operations"""
    
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
        primary = ann.get("vast.ai/gpu-type", "RTX 3060").strip()
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
        if region:
            offers = [o for o in offers if region.lower() in str(o.get("geolocation", "")).lower()]
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
            metadata=client.V1ObjectMeta(name=self.node_name, labels={"provider": "vast.ai", "node.kubernetes.io/instance-type": "gpu", "beta.kubernetes.io/arch": "amd64", "beta.kubernetes.io/os": "linux"}),
            spec=client.V1NodeSpec(taints=[client.V1Taint(key="virtual-kubelet.io/provider", value="vast", effect="NoSchedule"), client.V1Taint(key="vast.ai/gpu", effect="NoSchedule")]),
            status=client.V1NodeStatus(
                capacity={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                allocatable={"cpu": "16", "memory": "32Gi", "nvidia.com/gpu": "1", "pods": "10"},
                conditions=[client.V1NodeCondition(type="Ready", status="True", reason="VirtualKubeletReady", message="Virtual Kubelet is ready", last_heartbeat_time=datetime.now(timezone.utc), last_transition_time=datetime.now(timezone.utc))],
                addresses=[client.V1NodeAddress(type="InternalIP", address="10.0.0.1")],
                node_info=client.V1NodeSystemInfo(architecture="amd64", operating_system="linux", kernel_version="5.15.0", os_image="Ubuntu 22.04 LTS", container_runtime_version="docker://24.0.0", kubelet_version="v1.28.0-vk-vast-python", kube_proxy_version="v1.28.0-vk-vast-python", boot_id=os.getenv("BOOT_ID", f"vk-{int(datetime.now(timezone.utc).timestamp())}"), machine_id=os.getenv("MACHINE_ID", "vk-machine-id"), system_uuid=os.getenv("SYSTEM_UUID", "vk-system-uuid"))
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
    
    async def watch_pods(self):
        logger.info("Starting pod watcher", node_name=self.node_name)
        while self.running:
            try:
                w = watch.Watch()
                for event in w.stream(self.k8s_client.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={self.node_name}"):
                    event_type = event['type']
                    pod = event['object']
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
                    logger.warning("Watch expired, restarting", error=str(e))
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
                instance = {"id": f"mock_instance_{offer['id']}", "status": "running", "public_ip": offer.get("public_ip", "203.0.113.1"), "ssh_port": 22, "offer": offer}
                self.pod_instances[pod_name] = instance
                logger.info("Selected Vast.ai offer", pod_name=pod_name, gpu=offer.get("gpu_name"), price=offer.get("dph_total"), location=offer.get("geolocation"), offer_id=offer.get("id"))
                await self.update_pod_status_running(pod, instance)
        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))
    
    async def delete_pod(self, pod: V1Pod):
        pod_name = pod.metadata.name
        logger.info("Deleting pod from Vast.ai", pod_name=pod_name)
        if pod_name in self.pod_instances:
            instance = self.pod_instances.pop(pod_name)
            logger.info("Pod instance removed", pod_name=pod_name, instance_id=instance["id"])

    async def update_pod_status_running(self, pod: V1Pod, instance: Dict):
        try:
            container_statuses = []
            for container in pod.spec.containers:
                image = container.image or "unknown:latest"
                container_statuses.append(V1ContainerStatus(name=container.name, image=image, image_id=f"docker-pullable://{image}", ready=True, restart_count=0, state=client.V1ContainerState(running=client.V1ContainerStateRunning(started_at=datetime.now(timezone.utc)))))
            pod_status = V1PodStatus(phase="Running", pod_ip=instance.get("public_ip"), host_ip=instance.get("public_ip"), start_time=datetime.now(timezone.utc), conditions=[client.V1PodCondition(type="Initialized", status="True", last_transition_time=datetime.now(timezone.utc)), client.V1PodCondition(type="Ready", status="True", last_transition_time=datetime.now(timezone.utc)), client.V1PodCondition(type="ContainersReady", status="True", last_transition_time=datetime.now(timezone.utc)), client.V1PodCondition(type="PodScheduled", status="True", last_transition_time=datetime.now(timezone.utc))], container_statuses=container_statuses)
            self.k8s_client.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=client.V1Pod(status=pod_status))
            logger.info("Pod status updated to running", pod_name=pod.metadata.name)
        except Exception as e:
            logger.error("Failed to update pod status", pod_name=pod.metadata.name, error=str(e))

    async def update_pod_status_failed(self, pod: V1Pod, reason: str):
        try:
            pod_status = V1PodStatus(phase="Failed", reason=reason, message=f"Failed to create Vast.ai instance: {reason}", start_time=datetime.now(timezone.utc), conditions=[client.V1PodCondition(type="PodScheduled", status="True", last_transition_time=datetime.now(timezone.utc))])
            self.k8s_client.patch_namespaced_pod_status(name=pod.metadata.name, namespace=pod.metadata.namespace, body=client.V1Pod(status=pod_status))
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
            self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())
            logger.info("Node heartbeat loop started")
            await self.watch_pods()
        except Exception as e:
            logger.error("Virtual Kubelet crashed", error=str(e))
            raise
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
    
    def stop(self):
        logger.info("Stopping Virtual Kubelet")
        self.running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()


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
