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
from typing import Dict, List, Optional

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
        """Test API connectivity"""
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
    
    async def search_instances(self, gpu_type: str = "RTX3060") -> List[Dict]:
        """Search for available instances"""
        logger.info("Searching for Vast.ai instances", gpu_type=gpu_type)
        
        if not self.session:
            raise RuntimeError("Client session not initialized")
            
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {
            "verified": "true",
            "rentable": "true",
            "gpu_name": gpu_type,
        }
        
        try:
            async with self.session.get(f"{self.base_url}/bundles", headers=headers, params=params) as resp:
                if resp.status == 200:
                    offers = await resp.json()
                    logger.info("Found Vast.ai offers", count=len(offers.get("offers", [])))
                    return offers.get("offers", [])
                else:
                    logger.error("Failed to search instances", status_code=resp.status)
                    return []
        except Exception as e:
            logger.error("Error searching instances", error=str(e))
            return []
    
    async def create_instance(self, offer_id: str, pod: V1Pod) -> Optional[Dict]:
        """Create a new instance from an offer"""
        logger.info("Creating Vast.ai instance", offer_id=offer_id, pod_name=pod.metadata.name)
        
        # This would make the actual API call to create an instance
        # For now, return a mock instance
        return {
            "id": f"mock_instance_{offer_id}",
            "status": "running",
            "public_ip": "203.0.113.1",
            "ssh_port": 22,
        }


class VirtualKubelet:
    """Python Virtual Kubelet for Vast.ai"""
    
    def __init__(self, node_name: str, api_key: str):
        self.node_name = node_name
        self.api_key = api_key
        self.vast_client: Optional[VastAIClient] = None
        self.k8s_client: Optional[client.CoreV1Api] = None
        self.pod_instances: Dict[str, Dict] = {}  # pod_name -> instance_info
        self.running = False
        
    async def initialize(self):
        """Initialize the Virtual Kubelet"""
        logger.info("Initializing Virtual Kubelet", node_name=self.node_name)
        
        try:
            # Initialize Kubernetes client
            logger.info("Loading Kubernetes config")
            config.load_incluster_config()
            self.k8s_client = client.CoreV1Api()
            logger.info("Kubernetes client initialized")
            
            # Initialize Vast.ai client
            logger.info("Initializing Vast.ai client")
            self.vast_client = VastAIClient(self.api_key)
            
            # Test Vast.ai connection
            async with self.vast_client as vast:
                if not await vast.test_connection():
                    raise RuntimeError("Failed to connect to Vast.ai API")
            
            # Register virtual node
            await self.register_node()
            
            logger.info("Virtual Kubelet initialization complete")
            
        except Exception as e:
            logger.error("Failed to initialize Virtual Kubelet", error=str(e))
            raise
    
    async def register_node(self):
        """Register the virtual node with Kubernetes"""
        logger.info("Registering virtual node", node_name=self.node_name)
        
        # Create node object
        node = V1Node(
            metadata=client.V1ObjectMeta(
                name=self.node_name,
                labels={
                    "provider": "vast.ai",
                    "node.kubernetes.io/instance-type": "gpu",
                    "beta.kubernetes.io/arch": "amd64",
                    "beta.kubernetes.io/os": "linux",
                }
            ),
            spec=client.V1NodeSpec(
                taints=[
                    client.V1Taint(
                        key="virtual-kubelet.io/provider",
                        value="vast",
                        effect="NoSchedule"
                    ),
                    client.V1Taint(
                        key="vast.ai/gpu",
                        effect="NoSchedule"
                    )
                ]
            ),
            status=client.V1NodeStatus(
                capacity={
                    "cpu": "16",
                    "memory": "32Gi",
                    "nvidia.com/gpu": "1",
                    "pods": "10"
                },
                allocatable={
                    "cpu": "16", 
                    "memory": "32Gi",
                    "nvidia.com/gpu": "1",
                    "pods": "10"
                },
                conditions=[
                    client.V1NodeCondition(
                        type="Ready",
                        status="True",
                        reason="VirtualKubeletReady",
                        message="Virtual Kubelet is ready",
                        last_heartbeat_time=datetime.now(timezone.utc),
                        last_transition_time=datetime.now(timezone.utc)
                    )
                ],
                addresses=[
                    client.V1NodeAddress(type="InternalIP", address="10.0.0.1")
                ],
                node_info=client.V1NodeSystemInfo(
                    architecture="amd64",
                    operating_system="linux",
                    kernel_version="5.15.0",
                    os_image="Ubuntu 22.04 LTS",
                    container_runtime_version="docker://24.0.0",
                    kubelet_version="v1.28.0-vk-vast-python",
                    kube_proxy_version="v1.28.0-vk-vast-python",
                    boot_id=os.getenv("BOOT_ID", f"vk-{int(datetime.now(timezone.utc).timestamp())}"),
                    machine_id=os.getenv("MACHINE_ID", "vk-machine-id"),
                    system_uuid=os.getenv("SYSTEM_UUID", "vk-system-uuid"),
                )
            )
        )
        
        try:
            # Try to create the node
            self.k8s_client.create_node(node)
            logger.info("Virtual node registered successfully")
        except ApiException as e:
            if e.status == 409:  # Node already exists
                logger.info("Virtual node already exists, updating")
                self.k8s_client.patch_node(self.node_name, node)
            else:
                logger.error("Failed to register node", error=str(e))
                raise
    
    async def watch_pods(self):
        """Watch for pods scheduled to this node"""
        logger.info("Starting pod watcher", node_name=self.node_name)
        
        w = watch.Watch()
        try:
            for event in w.stream(
                self.k8s_client.list_pod_for_all_namespaces,
                field_selector=f"spec.nodeName={self.node_name}"
            ):
                event_type = event['type']
                pod = event['object']
                
                logger.info(
                    "Pod event received",
                    event_type=event_type,
                    pod_name=pod.metadata.name,
                    namespace=pod.metadata.namespace
                )
                
                try:
                    if event_type == "ADDED":
                        await self.create_pod(pod)
                    elif event_type == "DELETED":
                        await self.delete_pod(pod)
                    elif event_type == "MODIFIED":
                        await self.update_pod_status(pod)
                        
                except Exception as e:
                    logger.error(
                        "Error handling pod event",
                        event_type=event_type,
                        pod_name=pod.metadata.name,
                        error=str(e)
                    )
                    
        except Exception as e:
            logger.error("Error in pod watcher", error=str(e))
            raise
    
    async def create_pod(self, pod: V1Pod):
        """Create a pod on Vast.ai"""
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai", pod_name=pod_name)
        
        try:
            # Get GPU requirements from annotations
            gpu_type = pod.metadata.annotations.get("vast.ai/gpu-type", "RTX3060")
            
            async with VastAIClient(self.api_key) as vast:
                # Search for available instances
                offers = await vast.search_instances(gpu_type)
                
                if not offers:
                    logger.error("No Vast.ai offers available", gpu_type=gpu_type)
                    await self.update_pod_status_failed(pod, "No GPU instances available")
                    return
                
                # Select first available offer
                offer = offers[0]
                logger.info("Selected Vast.ai offer", offer_id=offer["id"])
                
                # Create instance
                instance = await vast.create_instance(offer["id"], pod)
                
                if instance:
                    # Store instance mapping
                    self.pod_instances[pod_name] = instance
                    logger.info("Pod created successfully", pod_name=pod_name, instance_id=instance["id"])
                    
                    # Update pod status to running
                    await self.update_pod_status_running(pod, instance)
                else:
                    logger.error("Failed to create Vast.ai instance", pod_name=pod_name)
                    await self.update_pod_status_failed(pod, "Failed to create instance")
                    
        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))
    
    async def delete_pod(self, pod: V1Pod):
        """Delete a pod from Vast.ai"""
        pod_name = pod.metadata.name
        logger.info("Deleting pod from Vast.ai", pod_name=pod_name)
        
        if pod_name in self.pod_instances:
            instance = self.pod_instances.pop(pod_name)
            logger.info("Pod instance removed", pod_name=pod_name, instance_id=instance["id"])
            # TODO: Make API call to destroy Vast.ai instance
    
    async def update_pod_status_running(self, pod: V1Pod, instance: Dict):
        """Update pod status to running"""
        pod_status = V1PodStatus(
            phase="Running",
            pod_ip=instance.get("public_ip"),
            conditions=[
                client.V1PodCondition(
                    type="Ready",
                    status="True",
                    last_transition_time=datetime.now(timezone.utc)
                )
            ],
            container_statuses=[
                V1ContainerStatus(
                    name=container.name,
                    ready=True,
                    restart_count=0,
                    state=client.V1ContainerState(
                        running=client.V1ContainerStateRunning(
                            started_at=datetime.now(timezone.utc)
                        )
                    )
                ) for container in pod.spec.containers
            ]
        )
        
        try:
            pod.status = pod_status
            self.k8s_client.patch_namespaced_pod_status(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                body=pod
            )
            logger.info("Pod status updated to running", pod_name=pod.metadata.name)
        except Exception as e:
            logger.error("Failed to update pod status", pod_name=pod.metadata.name, error=str(e))
    
    async def update_pod_status_failed(self, pod: V1Pod, reason: str):
        """Update pod status to failed"""
        pod_status = V1PodStatus(
            phase="Failed",
            reason=reason,
            message=f"Failed to create Vast.ai instance: {reason}"
        )
        
        try:
            pod.status = pod_status
            self.k8s_client.patch_namespaced_pod_status(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace, 
                body=pod
            )
            logger.info("Pod status updated to failed", pod_name=pod.metadata.name, reason=reason)
        except Exception as e:
            logger.error("Failed to update pod status", pod_name=pod.metadata.name, error=str(e))
    
    async def update_pod_status(self, pod: V1Pod):
        """Handle pod status updates"""
        # This would check instance status and update accordingly
        pass
    
    async def start_health_server(self):
        """Start HTTP health check server"""
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
        """Main run loop"""
        self.running = True
        logger.info("Starting Virtual Kubelet")
        
        try:
            # Initialize everything
            await self.initialize()
            
            # Start health server
            await self.start_health_server()
            
            # Start pod watcher
            await self.watch_pods()
            
        except Exception as e:
            logger.error("Virtual Kubelet crashed", error=str(e))
            raise
    
    def stop(self):
        """Stop the Virtual Kubelet"""
        logger.info("Stopping Virtual Kubelet")
        self.running = False


async def main():
    """Main entry point"""
    # Get configuration from environment
    node_name = os.getenv("NODE_NAME", "vast-gpu-node-python")
    api_key = os.getenv("VAST_API_KEY")
    
    if not api_key:
        logger.error("VAST_API_KEY environment variable is required")
        sys.exit(1)
    
    # Create and run Virtual Kubelet
    vk = VirtualKubelet(node_name, api_key)
    
    # Handle shutdown signals
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal", signal=signum)
        vk.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the Virtual Kubelet
    try:
        await vk.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error("Virtual Kubelet failed", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    # Use uvloop for better async performance
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    
    asyncio.run(main())