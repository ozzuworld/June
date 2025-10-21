#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai
Adds node registration, status updates, and lease heartbeats so the node stays Ready
"""
import asyncio
import os
import re
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import aiohttp
import structlog
from aiohttp import web
from kubernetes import client as k8s_client, config as k8s_config
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
VAST_API_BASE = "https://console.vast.ai/api/v0"
VAST_API_KEY = os.getenv("VAST_API_KEY")
NODE_NAME = os.getenv("NODE_NAME", "vast-gpu-node-python")

# Rate limiting for instance creation
from asyncio import Semaphore
INSTANCE_BUY_SEMAPHORE = Semaphore(2)


class VastAIClient:
    """Client for Vast.ai API with proper error handling"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = VAST_API_BASE
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _parse_disk_space(self, disk_str: str) -> float:
        """Parse disk space string like '50GB' or '50' to float"""
        if isinstance(disk_str, (int, float)):
            return float(disk_str)
        
        # Remove units and convert to float
        import re as _re
        match = _re.match(r'(\d+(?:\.\d+)?)', str(disk_str))
        if match:
            return float(match.group(1))
        return 50.0  # default
    
    async def search_offers(
        self, 
        gpu_type: str = "RTX 3060",
        max_price: float = 0.50,
        region: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for available GPU offers"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        
        # Build search query
        params = {
            "rentable": "true",
            "verified": "true",
            "gpu_name": gpu_type,
            "dph_lte": max_price,
            "reliability_gte": 0.90,
            "inet_down_gte": 100,
        }
        
        if region:
            params["geolocation"] = region
        
        endpoint = "/bundles"
        
        try:
            async with self.session.get(f"{self.base_url}{endpoint}", params=params) as resp:
                content_type = resp.headers.get('Content-Type', '')
                
                # Check if response is JSON
                if 'application/json' not in content_type.lower():
                    text = await resp.text()
                    logger.error(
                        "search_offers: Non-JSON response",
                        status_code=resp.status,
                        content_type=content_type,
                        response_preview=text[:500]
                    )
                    return []
                
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(
                        "search_offers failed",
                        status_code=resp.status,
                        response_preview=text[:500]
                    )
                    return []
                
                data = await resp.json()
                offers = data if isinstance(data, list) else []
                
                logger.info("search_offers success", offer_count=len(offers))
                return offers
                
        except Exception as e:
            logger.error("search_offers exception", error=str(e))
            return []
    
    async def buy_instance(
        self, 
        ask_id: int, 
        pod_annotations: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Create a new Vast.ai instance with proper error handling"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        
        # Parse disk space properly
        disk_str = pod_annotations.get("vast.ai/disk", "50")
        disk_gb = self._parse_disk_space(disk_str)
        
        payload = {
            "image": pod_annotations.get("vast.ai/image", "pytorch/pytorch:2.2.0-cuda12.1-cudnn8-devel"),
            "disk": disk_gb,
            "runtype": pod_annotations.get("vast.ai/runtype", "ssh_direct"),
        }
        
        # Add optional fields
        if "vast.ai/env" in pod_annotations:
            payload["env"] = pod_annotations["vast.ai/env"]
        
        if "vast.ai/price-max" in pod_annotations:
            try:
                payload["price"] = float(pod_annotations["vast.ai/price-max"])
            except ValueError:
                pass
        
        if "vast.ai/onstart-cmd" in pod_annotations:
            payload["onstart_cmd"] = pod_annotations["vast.ai/onstart-cmd"]
        
        endpoint = f"/asks/{ask_id}/"  # Correct Vast.ai endpoint
        
        try:
            # Use PUT method as per Vast.ai API spec
            async with self.session.put(
                f"{self.base_url}{endpoint}", 
                json=payload
            ) as resp:
                body = await resp.read()
                content_type = resp.headers.get('Content-Type', '')
                
                # Log response for debugging
                text_preview = body.decode(errors='ignore')[:500]
                logger.info(
                    "Instance creation response",
                    ask_id=ask_id,
                    status_code=resp.status,
                    content_type=content_type,
                    response_preview=text_preview
                )
                
                # Check for non-2xx status
                if resp.status not in (200, 201):
                    logger.error(
                        "buy_instance failed (non-2xx)",
                        ask_id=ask_id,
                        status_code=resp.status,
                        content_type=content_type,
                        response=text_preview
                    )
                    return None
                
                # Parse response based on content type
                data = None
                if 'application/json' in content_type.lower():
                    try:
                        data = await resp.json()
                    except Exception as je:
                        logger.error(
                            "Failed to parse JSON response",
                            error=str(je),
                            response_preview=text_preview
                        )
                        return None
                else:
                    # Plain text contract ID (legacy API format)
                    stripped = text_preview.strip()
                    if stripped.isdigit():
                        data = {"new_contract": int(stripped)}
                    else:
                        logger.error(
                            "Non-JSON, non-numeric response",
                            response_preview=text_preview
                        )
                        return None
                
                # Extract contract ID
                instance_id = data.get("new_contract")
                if not instance_id:
                    logger.error(
                        "Missing new_contract in response",
                        data=str(data)[:300]
                    )
                    return None
                
                logger.info(
                    "Instance creation initiated",
                    ask_id=ask_id,
                    instance_id=instance_id
                )
                return data
                
        except Exception as e:
            logger.error(
                "buy_instance exception",
                ask_id=ask_id,
                error=str(e),
                endpoint=endpoint
            )
            return None
    
    async def poll_instance_ready(
        self, 
        instance_id: int, 
        timeout_seconds: int = 300
    ) -> Optional[Dict[str, Any]]:
        """Poll instance until it's ready"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        
        endpoint = f"/instances/{instance_id}"
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                async with self.session.get(f"{self.base_url}{endpoint}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        status = data.get("actual_status")
                        
                        if status == "running" and data.get("ssh_host"):
                            logger.info(
                                "Instance ready",
                                instance_id=instance_id,
                                ssh_host=data.get("ssh_host")
                            )
                            return data
                        
                        logger.debug(
                            "Instance not ready yet",
                            instance_id=instance_id,
                            status=status
                        )
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.warning(
                    "Error polling instance",
                    instance_id=instance_id,
                    error=str(e)
                )
                await asyncio.sleep(10)
        
        logger.error(
            "Instance readiness timeout",
            instance_id=instance_id,
            timeout_seconds=timeout_seconds
        )
        return None
    
    async def delete_instance(self, instance_id: int) -> bool:
        """Delete an instance"""
        if not self.session:
            raise RuntimeError("Client session not initialized")
        
        endpoint = f"/instances/{instance_id}"
        
        try:
            async with self.session.delete(f"{self.base_url}{endpoint}") as resp:
                if resp.status in (200, 404):
                    logger.info("Instance deleted", instance_id=instance_id)
                    return True
                else:
                    logger.error(
                        "Failed to delete instance",
                        instance_id=instance_id,
                        status_code=resp.status
                    )
                    return False
        except Exception as e:
            logger.error(
                "delete_instance exception",
                instance_id=instance_id,
                error=str(e)
            )
            return False


class VirtualKubelet:
    """Virtual Kubelet implementation for Vast.ai with node heartbeats"""
    
    def __init__(self, api_key: str, node_name: str):
        self.api_key = api_key
        self.node_name = node_name
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        
        # Initialize Kubernetes client
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        
        self.v1 = k8s_client.CoreV1Api()
        self.coordination = k8s_client.CoordinationV1Api()
        
        logger.info(
            "VirtualKubelet initialized",
            node_name=node_name,
            api_key_length=len(api_key)
        )
    
    # ----------------------- Node registration & heartbeats -----------------------
    def _now(self):
        return datetime.now(timezone.utc)

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
                annotations={
                    "node.alpha.kubernetes.io/ttl": "0"
                }
            ),
            spec=k8s_client.V1NodeSpec(
                taints=[
                    k8s_client.V1Taint(key="vast.ai/gpu", effect="NoSchedule"),
                    k8s_client.V1Taint(key="virtual-kubelet.io/provider", value="vast", effect="NoSchedule"),
                ]
            ),
            status=k8s_client.V1NodeStatus(
                capacity={
                    "cpu": "16",
                    "memory": "32Gi",
                    "nvidia.com/gpu": "1",
                    "pods": "10",
                },
                allocatable={
                    "cpu": "16",
                    "memory": "32Gi",
                    "nvidia.com/gpu": "1",
                    "pods": "10",
                },
                addresses=[
                    k8s_client.V1NodeAddress(type="InternalIP", address="10.0.0.1")
                ],
                node_info=k8s_client.V1NodeSystemInfo(
                    machine_id="vk-machine-id",
                    system_uuid="vk-system-uuid",
                    boot_id=f"vk-{int(time.time())}",
                    kernel_version="5.15.0",
                    os_image="Ubuntu 22.04 LTS",
                    operating_system="linux",
                    architecture="amd64",
                    container_runtime_version="docker://24.0.0",
                    kubelet_version="v1.28.0-vk-vast-python",
                    kube_proxy_version="v1.28.0-vk-vast-python",
                ),
                conditions=[
                    k8s_client.V1NodeCondition(
                        type="Ready",
                        status="True",
                        last_heartbeat_time=self._now(),
                        last_transition_time=self._now(),
                        reason="KubeletReady",
                        message="kubelet is posting ready status",
                    ),
                    k8s_client.V1NodeCondition(
                        type="MemoryPressure",
                        status="False",
                        last_heartbeat_time=self._now(),
                        last_transition_time=self._now(),
                        reason="KubeletHasSufficientMemory",
                        message="kubelet has sufficient memory available",
                    ),
                    k8s_client.V1NodeCondition(
                        type="DiskPressure",
                        status="False",
                        last_heartbeat_time=self._now(),
                        last_transition_time=self._now(),
                        reason="KubeletHasNoDiskPressure",
                        message="kubelet has no disk pressure",
                    ),
                    k8s_client.V1NodeCondition(
                        type="PIDPressure",
                        status="False",
                        last_heartbeat_time=self._now(),
                        last_transition_time=self._now(),
                        reason="KubeletHasSufficientPID",
                        message="kubelet has sufficient PID available",
                    ),
                ],
            ),
        )

    async def register_node(self):
        node = self._base_node_object()
        try:
            self.v1.create_node(body=node)
            logger.info("Node registered successfully", node_name=self.node_name)
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.info("Node already exists", node_name=self.node_name)
            else:
                logger.error("Failed to register node", error=str(e))
                raise

    async def update_node_status(self):
        try:
            node = self.v1.read_node(name=self.node_name)
            # Refresh heartbeat timestamps
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
                # Update renew time
                lease.spec.renew_time = self._now()
                lease.spec.holder_identity = self.node_name
                self.coordination.replace_namespaced_lease(name=lease_name, namespace=namespace, body=lease)
            except ApiException as e:
                if e.status == 404:
                    lease = k8s_client.V1Lease(
                        metadata=k8s_client.V1ObjectMeta(name=lease_name, namespace=namespace),
                        spec=k8s_client.V1LeaseSpec(
                            holder_identity=self.node_name,
                            lease_duration_seconds=40,
                            renew_time=self._now(),
                        ),
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

    # ----------------------- Vast.ai Pod lifecycle -----------------------
    def _parse_annotations(self, pod) -> tuple:
        annotations = pod.metadata.annotations or {}
        gpu_primary = annotations.get("vast.ai/gpu-type", "RTX 3060")
        gpu_fallbacks = annotations.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary]
        if gpu_fallbacks:
            gpu_list.extend([g.strip() for g in gpu_fallbacks.split(",")])
        price_max = float(annotations.get("vast.ai/price-max", "0.50"))
        region = annotations.get("vast.ai/region")
        return gpu_list, price_max, region
    
    async def _find_offer(
        self,
        vast: VastAIClient,
        gpu_list: List[str],
        price_max: float,
        region: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        for gpu_type in gpu_list:
            logger.info("Searching offers", gpu_type=gpu_type)
            offers = await vast.search_offers(gpu_type=gpu_type, max_price=price_max, region=region)
            if offers:
                offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                best_offer = offers_sorted[0]
                logger.info("Offer match found", gpu_type=gpu_type, offer_id=best_offer.get("id"), price=best_offer.get("dph_total"))
                return best_offer
        logger.warning("No offers found", gpu_list=gpu_list)
        return None
    
    async def create_pod(self, pod):
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai", pod_name=pod_name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_status_failed(pod, "No GPU instances available")
                    return
                async with INSTANCE_BUY_SEMAPHORE:
                    buy_result = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})
                if not buy_result:
                    await self.update_pod_status_failed(pod, "Failed to create instance")
                    return
                instance_id = buy_result.get("new_contract")
                if not instance_id:
                    await self.update_pod_status_failed(pod, "Invalid instance ID in response")
                    return
                try:
                    instance_id_int = int(instance_id)
                except (ValueError, TypeError):
                    await self.update_pod_status_failed(pod, f"Invalid instance ID format: {instance_id}")
                    return
                ready_instance = await vast.poll_instance_ready(instance_id_int, timeout_seconds=300)
                if not ready_instance:
                    await vast.delete_instance(instance_id_int)
                    await self.update_pod_status_failed(pod, "Instance failed to start")
                    return
                instance = {
                    "id": instance_id_int,
                    "status": "running",
                    "public_ip": ready_instance.get("public_ipaddr"),
                    "ssh_port": ready_instance.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready_instance,
                }
                self.pod_instances[pod_name] = instance
                await self.update_pod_status_running(pod, instance)
                logger.info("Pod created successfully", pod_name=pod_name, instance_id=instance_id_int)
        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
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
            logger.info("Pod deleted", pod_name=pod_name, instance_id=instance["id"])
        except Exception as e:
            logger.error("Error deleting pod", pod_name=pod_name, error=str(e))


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
    """Main entry point"""
    if not VAST_API_KEY:
        logger.error("VAST_API_KEY environment variable required")
        return
    
    # Initialize Virtual Kubelet
    vk = VirtualKubelet(VAST_API_KEY, NODE_NAME)

    # Register node before serving
    await vk.register_node()
    
    # Start HTTP server for health checks
    app = await build_app(vk)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10255)
    await site.start()
    
    logger.info("Virtual Kubelet started", node_name=NODE_NAME)
    
    # Start heartbeat loop
    heartbeat_task = asyncio.create_task(vk.heartbeat_loop())
    
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        logger.info("Heartbeat task cancelled")
    except KeyboardInterrupt:
        logger.info("Shutting down")
        heartbeat_task.cancel()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
