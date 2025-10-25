#!/usr/bin/env python3
"""
Virtual Kubelet Provider for Vast.ai (Enhanced)
- Rate limiting and API management
- Comprehensive error handling
- Enhanced pod lifecycle management  
- Resource monitoring
- Configuration validation
- Single instance limit for development
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

# Configuration with validation
class VastProviderConfig:
    def __init__(self):
        self.api_key = os.getenv("VAST_API_KEY")
        self.node_name = os.getenv("NODE_NAME", "vast-gpu-node-python")
        self.max_instances = int(os.getenv("MAX_INSTANCES", "1"))  # Keep at 1 for development
        self.rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM", "30"))
        self.default_gpu = os.getenv("DEFAULT_GPU_TYPE", "RTX 4060")
        self.region_preference = os.getenv("REGION_PREFERENCE", "US")
        self.force_gpu_type = os.getenv("FORCE_GPU_TYPE")
        self.force_image = os.getenv("FORCE_IMAGE")
        self.force_price_max = os.getenv("FORCE_PRICE_MAX")
        
    def validate(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        if not self.api_key:
            errors.append("VAST_API_KEY is required")
        
        if self.max_instances < 1:
            errors.append("MAX_INSTANCES must be >= 1")
            
        if self.rate_limit_rpm < 1:
            errors.append("RATE_LIMIT_RPM must be >= 1")
        
        return errors

# Rate limiter for Vast.ai API
class VastAPIRateLimiter:
    def __init__(self, requests_per_minute=30):
        self.semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
        self.timestamps = []
        self.rpm_limit = requests_per_minute
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire rate limit token"""
        async with self.semaphore:
            async with self.lock:
                now = time.time()
                # Clean timestamps older than 1 minute
                self.timestamps = [ts for ts in self.timestamps if now - ts < 60]
                
                # Check if we need to wait
                if len(self.timestamps) >= self.rpm_limit:
                    sleep_time = 60 - (now - self.timestamps[0])
                    if sleep_time > 0:
                        logger.info("Rate limit reached, waiting", sleep_time=sleep_time)
                        await asyncio.sleep(sleep_time)
                        # Clean again after sleep
                        now = time.time()
                        self.timestamps = [ts for ts in self.timestamps if now - ts < 60]
                
                self.timestamps.append(now)

# Enhanced metrics collection
class VastProviderMetrics:
    def __init__(self):
        self.instance_creation_times = []
        self.api_call_latencies = []
        self.error_counts = defaultdict(int)
        self.last_health_check = {}
        
    def record_instance_creation(self, duration: float):
        self.instance_creation_times.append({
            'timestamp': time.time(),
            'duration': duration
        })
        # Keep only last 100 records
        self.instance_creation_times = self.instance_creation_times[-100:]
    
    def record_api_latency(self, endpoint: str, duration: float):
        self.api_call_latencies.append({
            'timestamp': time.time(),
            'endpoint': endpoint,
            'duration': duration
        })
        # Keep only last 200 records
        self.api_call_latencies = self.api_call_latencies[-200:]
    
    def record_error(self, error_type: str):
        self.error_counts[error_type] += 1

class VastAIClient:
    def __init__(self, api_key: str, rate_limiter: VastAPIRateLimiter, metrics: VastProviderMetrics):
        self.api_key = api_key
        self.rate_limiter = rate_limiter
        self.metrics = metrics
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
        
        # Apply rate limiting
        await self.rate_limiter.acquire()
        
        start_time = time.time()
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *([self.cli_path] + args), 
                stdout=asyncio.subprocess.PIPE, 
                stderr=asyncio.subprocess.PIPE, 
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            out, err = await proc.communicate()
            
            # Record API latency
            duration = time.time() - start_time
            self.metrics.record_api_latency(args[0] if args else 'unknown', duration)
            
            if proc.returncode != 0:
                em = (err.decode() or "").strip()
                error_response = self._categorize_error(em)
                self.metrics.record_error(error_response.get('category', 'unknown'))
                return error_response
                
            txt = (out.decode() or "").strip()
            try:
                return {"data": json.loads(txt)} if txt and txt[0] in "[{" else {"data": txt}
            except Exception:
                return {"data": txt}
                
        except Exception as e:
            duration = time.time() - start_time
            self.metrics.record_api_latency(args[0] if args else 'unknown', duration)
            self.metrics.record_error('exception')
            return {"error": str(e), "category": "exception"}
    
    def _categorize_error(self, error_message: str) -> Dict[str, Any]:
        """Categorize errors for better handling"""
        em_lower = error_message.lower()
        
        # Instance gone/deleted
        if any(term in em_lower for term in ["not found", "does not exist", "404"]):
            return {"gone": True, "category": "gone"}
        
        # Rate limiting
        if any(term in em_lower for term in ["rate limit", "too many requests", "429"]):
            return {"rate_limited": True, "category": "rate_limit", "error": error_message}
        
        # Network issues
        if any(term in em_lower for term in ["connection", "timeout", "network", "dns"]):
            return {"network_error": True, "category": "network", "error": error_message}
        
        # Vast API bugs (transient errors)
        if "show__instance" in error_message and "start_date" in error_message:
            return {"transient_error": True, "category": "transient"}
        
        # Generic error
        return {"error": error_message, "category": "generic"}
    
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
    
    async def search_offers(self, gpu_type: str, max_price: float, region: Optional[str]) -> List[Dict[str, Any]]:
        gpu_cli = gpu_type.replace(" ", "_")
        parts = [
            "rentable=true",
            "verified=true", 
            "rented=false",
            f"gpu_name={gpu_cli}",
            f"dph<={max_price:.2f}",
            "reliability>=0.70",
            "inet_down>=50",
            "inet_up>=20"
        ]
        
        if region:
            r = region.strip().lower()
            if r in ("north america", "na"): 
                parts.append("geolocation in [US,CA,MX]")
            elif r in ("us", "usa", "united states"): 
                parts.append("geolocation=US")
            elif r in ("canada", "ca"): 
                parts.append("geolocation=CA")
            elif r in ("europe", "eu"): 
                parts.append("geolocation in [DE,FR,GB,IT,ES]")
            elif "=" in region: 
                parts.append(region)
                
        res = await self._run(["search", "offers", "--raw", "--no-default", " ".join(parts), "-o", "dph+"])
        
        if "error" in res or "rate_limited" in res or "network_error" in res:
            return []
            
        data = res.get("data", [])
        return data if isinstance(data, list) else []
    
    async def buy_instance(self, ask_id: int, ann: Dict[str,str], pod) -> Optional[Dict[str, Any]]:
        image = config.force_image or ann.get("vast.ai/image", "ozzuworld/june-multi-gpu:latest")
        disk_str = ann.get("vast.ai/disk", "50")
        
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except Exception:
            disk_gb = 50.0
            
        args = ["create", "instance", str(ask_id), "--raw", "--image", image, "--disk", str(int(disk_gb))]
        
        if "vast.ai/onstart-cmd" in ann: 
            args += ["--onstart-cmd", ann["vast.ai/onstart-cmd"]]
        
        # Build environment string with Tailscale support
        env_parts = []
        env_parts.append("-p 8000:8000 -p 8001:8001")
        env_parts.append("--privileged --cap-add=NET_ADMIN --device /dev/net/tun")
        
        tailscale_env = self._build_tailscale_env_string(pod)
        if tailscale_env:
            env_parts.append(tailscale_env)
            
        if "vast.ai/env" in ann:
            env_parts.append(ann["vast.ai/env"])
            
        env_string = " ".join(env_parts)
        args += ["--env", env_string]
        
        logger.info("Creating Vast.ai instance", image=image, env=env_string, ask_id=ask_id)
        
        res = await self._run(args)
        
        # Handle various response types
        if "rate_limited" in res:
            return {"rate_limited": True}
        if "error" in res:
            return None
            
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            return {"new_contract": int(data)}
        if isinstance(data, dict) and "new_contract" in data:
            return data
            
        return None
    
    async def show_instance(self, instance_id: int) -> Dict[str, Any]:
        return await self._run(["show", "instance", str(instance_id), "--raw"])
    
    async def destroy_instance(self, instance_id: int) -> Dict[str, Any]:
        return await self._run(["destroy", "instance", str(instance_id)])

# Global configuration instance
config = VastProviderConfig()

class VirtualKubelet:
    def __init__(self, config: VastProviderConfig):
        self.config = config
        self.node_name = config.node_name
        self.pod_instances: Dict[str, Dict[str, Any]] = {}
        self.instance_keys: Dict[str, str] = {}  # desired_key -> pod_name
        self.recreate_backoff: Dict[str, float] = defaultdict(float)
        
        # Initialize components
        self.metrics = VastProviderMetrics()
        self.rate_limiter = VastAPIRateLimiter(config.rate_limit_rpm)
        self.vast_client = VastAIClient(config.api_key, self.rate_limiter, self.metrics)
        
        # Kubernetes setup
        try:
            k8s_konfig.load_incluster_config()
        except Exception:
            k8s_konfig.load_kube_config()
            
        self.v1 = k8s_client.CoreV1Api()
        
        # Pass k8s client to vast client for secret access
        self.vast_client.v1 = self.v1
        
        logger.info("VirtualKubelet initialized", 
                   node=self.node_name, 
                   max_instances=config.max_instances,
                   ssh_available=SSH_AVAILABLE)
    
    def _now(self):
        return datetime.now(timezone.utc)
    
    def _is_target_pod(self, pod) -> bool:
        try:
            return (pod and pod.spec and 
                   pod.spec.node_name == self.node_name and 
                   pod.metadata.deletion_timestamp is None)
        except Exception:
            return False
    
    def get_desired_key(self, pod):
        if pod.metadata.owner_references:
            return pod.metadata.owner_references[0].uid
        return pod.metadata.uid
    
    async def create_pod(self, pod):
        """Enhanced pod creation with comprehensive error handling"""
        pod_name = pod.metadata.name
        desired_key = self.get_desired_key(pod)
        now = time.time()
        
        logger.info("Creating pod", pod=pod_name, desired_key=desired_key)
        
        # Development safety: single instance cap
        if len(self.pod_instances) >= self.config.max_instances:
            logger.info("Instance cap reached, not provisioning", 
                       current=len(self.pod_instances),
                       max=self.config.max_instances)
            await self.update_pod_status_failed(pod, "Instance limit reached")
            return
        
        # Check if already tracking
        if (self.instance_keys.get(desired_key) and 
            self.pod_instances.get(self.instance_keys[desired_key])):
            logger.info("Instance already tracked", key=desired_key)
            return
        
        # Respect backoff period
        if now < self.recreate_backoff[pod_name]:
            delay = int(self.recreate_backoff[pod_name] - now)
            logger.debug("Delaying recreation due to backoff", pod=pod_name, delay=delay)
            return
        
        creation_start = time.time()
        
        try:
            # Parse pod annotations
            gpu_list, price_max, region = self._parse_annotations(pod)
            
            # Find available offer
            offer = await self._find_offer(gpu_list, price_max, region)
            if not offer:
                await self.update_pod_status_failed(pod, "No GPU offers available")
                return
            
            # Create instance
            buy_result = await self.vast_client.buy_instance(
                offer["id"], 
                pod.metadata.annotations or {}, 
                pod
            )
            
            if not buy_result:
                await self.update_pod_status_failed(pod, "Failed to create instance")
                return
            
            if buy_result.get("rate_limited"):
                logger.warning("Rate limited during instance creation", pod=pod_name)
                self.recreate_backoff[pod_name] = time.time() + 60
                await self.update_pod_status_failed(pod, "Rate limited - will retry")
                return
            
            if not buy_result.get("new_contract"):
                await self.update_pod_status_failed(pod, "Invalid instance response")
                return
            
            instance_id = int(buy_result["new_contract"])
            
            # Track instance
            self.pod_instances[pod_name] = {
                "id": instance_id,
                "state": "provisioning",
                "created": time.time(),
                "offer": offer,
                "gone": False
            }
            self.instance_keys[desired_key] = pod_name
            
            logger.info("Instance created, waiting for ready state", 
                       pod=pod_name, 
                       instance_id=instance_id)
            
            # Wait for instance to be ready
            await self._wait_for_instance_ready(pod, pod_name, desired_key, instance_id)
            
            # Record creation time
            creation_duration = time.time() - creation_start
            self.metrics.record_instance_creation(creation_duration)
            
        except Exception as e:
            logger.error("Pod creation failed with exception", 
                        pod=pod_name, 
                        error=str(e))
            await self._handle_instance_fail(pod, pod_name, desired_key, f"Creation error: {e}")
    
    async def _wait_for_instance_ready(self, pod, pod_name: str, desired_key: str, instance_id: int):
        """Wait for instance to reach running state with enhanced error handling"""
        start_time = time.time()
        timeout = 600  # 10 minutes
        
        while time.time() - start_time < timeout:
            try:
                show_result = await self.vast_client.show_instance(instance_id)
                
                # Handle different response types
                if show_result.get("gone"):
                    await self._handle_instance_gone(pod, pod_name, desired_key)
                    return
                
                if show_result.get("rate_limited"):
                    logger.info("Rate limited during instance check", pod=pod_name)
                    await asyncio.sleep(60)
                    continue
                
                if show_result.get("network_error"):
                    logger.warning("Network error during instance check", pod=pod_name)
                    await asyncio.sleep(30)
                    continue
                
                if show_result.get("transient_error"):
                    logger.debug("Transient error during instance check", pod=pod_name)
                    await asyncio.sleep(15)
                    continue
                
                # Check if running
                data = show_result.get("data")
                if isinstance(data, dict):
                    status = data.get("actual_status")
                    ssh_host = data.get("ssh_host")
                    
                    if status == "running" and ssh_host:
                        # Instance is ready
                        self.pod_instances[pod_name].update({
                            "state": "running",
                            "instance_data": data
                        })
                        await self.update_pod_status_running(pod, self.pod_instances[pod_name])
                        logger.info("Instance is running", 
                                   pod=pod_name, 
                                   ssh_host=ssh_host,
                                   elapsed=int(time.time() - start_time))
                        return
                    
                    elif status in ("exited", "stopped"):
                        await self._handle_instance_fail(pod, pod_name, desired_key, 
                                                       f"Instance failed with status: {status}")
                        return
                
                await asyncio.sleep(15)
                
            except Exception as e:
                logger.error("Error during instance wait", pod=pod_name, error=str(e))
                await asyncio.sleep(30)
        
        # Timeout reached
        await self._handle_instance_fail(pod, pod_name, desired_key, "Provisioning timeout")
    
    async def _handle_instance_gone(self, pod, pod_name: str, desired_key: str):
        """Handle externally deleted instances"""
        logger.info("Instance deleted externally, scheduling recreate", pod=pod_name)
        
        self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = time.time() + 120  # 2 minute cooldown
        
        await self.update_pod_status_failed(pod, "External deletion - will retry")
    
    async def _handle_instance_fail(self, pod, pod_name: str, desired_key: str, reason: str):
        """Handle instance failures"""
        logger.warning("Instance provisioning failed", pod=pod_name, reason=reason)
        
        # Cleanup tracking
        instance = self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = time.time() + 120
        
        # Try to destroy instance if it exists
        if instance and instance.get("id"):
            try:
                await self.vast_client.destroy_instance(instance["id"])
            except Exception as e:
                logger.error("Failed to destroy failed instance", 
                           instance_id=instance["id"], 
                           error=str(e))
        
        await self.update_pod_status_failed(pod, reason)
    
    async def update_pod_status_failed(self, pod, reason: str):
        """Update pod status to Failed with reason"""
        try:
            if not pod.status:
                pod.status = k8s_client.V1PodStatus()
                
            pod.status.phase = "Failed"
            pod.status.reason = reason
            pod.status.message = f"Vast.ai provider: {reason}"
            
            self.v1.patch_namespaced_pod_status(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                body=pod
            )
            
            logger.info("Updated pod status to Failed", pod=pod.metadata.name, reason=reason)
            
        except Exception as e:
            logger.error("Failed to update pod status", pod=pod.metadata.name, error=str(e))
    
    async def update_pod_status_running(self, pod, instance):
        """Update pod status to Running with comprehensive conditions"""
        try:
            if not pod.status:
                pod.status = k8s_client.V1PodStatus()
                
            instance_data = instance.get("instance_data", {})
            
            pod.status.phase = "Running"
            pod.status.pod_ip = instance_data.get("public_ip")
            pod.status.host_ip = instance_data.get("ssh_host")
            pod.status.start_time = self._now()
            
            # Add conditions
            conditions = [
                ("PodScheduled", "True", "Scheduled", "Pod has been scheduled to a node"),
                ("Initialized", "True", "PodCompleted", "All init containers have completed"),
                ("Ready", "True", "PodReady", "Pod is ready to serve traffic"),
                ("ContainersReady", "True", "ContainersReady", "All containers are ready")
            ]
            
            pod.status.conditions = []
            for condition_type, status, reason, message in conditions:
                pod.status.conditions.append(
                    k8s_client.V1PodCondition(
                        type=condition_type,
                        status=status,
                        last_transition_time=self._now(),
                        reason=reason,
                        message=message
                    )
                )
            
            self.v1.patch_namespaced_pod_status(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                body=pod
            )
            
            logger.info("Updated pod status to Running", 
                       pod=pod.metadata.name,
                       pod_ip=pod.status.pod_ip,
                       host_ip=pod.status.host_ip)
            
        except Exception as e:
            logger.error("Failed to update pod status", pod=pod.metadata.name, error=str(e))
    
    async def delete_pod(self, pod):
        """Delete pod and cleanup Vast.ai instance"""
        pod_name = pod.metadata.name
        desired_key = self.get_desired_key(pod)
        
        logger.info("Deleting pod", pod=pod_name)
        
        instance = self.pod_instances.get(pod_name)
        if instance:
            try:
                # Destroy the Vast.ai instance
                await self.vast_client.destroy_instance(instance["id"])
                logger.info("Destroyed Vast.ai instance", 
                           pod=pod_name, 
                           instance_id=instance["id"])
            except Exception as e:
                logger.error("Failed to destroy instance", 
                           pod=pod_name, 
                           instance_id=instance["id"],
                           error=str(e))
        
        # Cleanup tracking
        self.pod_instances.pop(pod_name, None)
        self.instance_keys.pop(desired_key, None)
        self.recreate_backoff[pod_name] = 0
    
    def _parse_annotations(self, pod) -> tuple:
        """Parse pod annotations for Vast.ai configuration"""
        ann = pod.metadata.annotations or {}
        
        gpu_primary = (self.config.force_gpu_type or 
                      ann.get("vast.ai/gpu-type", self.config.default_gpu))
        gpu_fallbacks = ann.get("vast.ai/gpu-fallbacks", "")
        gpu_list = [gpu_primary] + ([g.strip() for g in gpu_fallbacks.split(",")] 
                                   if gpu_fallbacks else [])
        
        price_max = float(self.config.force_price_max or 
                         ann.get("vast.ai/price-max", "0.20"))
        region = ann.get("vast.ai/region", self.config.region_preference)
        
        return gpu_list, price_max, region
    
    async def _find_offer(self, gpu_list: List[str], price_max: float, 
                         region: Optional[str]) -> Optional[Dict[str, Any]]:
        """Find best available offer"""
        for gpu in (gpu_list[:3] if len(gpu_list) > 3 else gpu_list):
            try:
                offers = await self.vast_client.search_offers(gpu, price_max, region)
                if offers:
                    # Sort by price and return cheapest
                    offers_sorted = sorted(offers, key=lambda x: x.get("dph_total", 999))
                    return offers_sorted[0]
            except Exception as e:
                logger.warning("Failed to search offers", gpu=gpu, error=str(e))
                continue
        
        return None
    
    async def register_node(self):
        """Register this Virtual Kubelet as a Kubernetes node"""
        try:
            # Check if node exists
            try:
                node = self.v1.read_node(name=self.node_name)
                logger.info("Node already registered", node=self.node_name)
                return
            except ApiException as e:
                if e.status != 404:
                    logger.error("Error checking node", error=str(e))
                    return
            
            # Create new node
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
                        "vast.ai/provider": "vast-python"
                    },
                    annotations={
                        "node.alpha.kubernetes.io/ttl": "0",
                        "vast.ai/max-instances": str(self.config.max_instances),
                        "vast.ai/provider-version": "2.0.0"
                    }
                ),
                spec=k8s_client.V1NodeSpec(
                    taints=[
                        k8s_client.V1Taint(
                            key="virtual-kubelet.io/provider",
                            value="vast-ai",
                            effect="NoSchedule"
                        )
                    ]
                ),
                status=k8s_client.V1NodeStatus(
                    addresses=[
                        k8s_client.V1NodeAddress(type="InternalIP", address="127.0.0.1")
                    ],
                    allocatable={
                        "cpu": "8",
                        "memory": "32Gi",
                        "nvidia.com/gpu": "1",
                        "ephemeral-storage": "100Gi",
                        "pods": str(self.config.max_instances)
                    },
                    capacity={
                        "cpu": "8", 
                        "memory": "32Gi",
                        "nvidia.com/gpu": "1",
                        "ephemeral-storage": "100Gi",
                        "pods": str(self.config.max_instances)
                    },
                    conditions=[
                        k8s_client.V1NodeCondition(
                            type="Ready",
                            status="True",
                            last_heartbeat_time=self._now(),
                            last_transition_time=self._now(),
                            reason="VirtualKubeletReady",
                            message="Virtual Kubelet is ready"
                        )
                    ],
                    node_info=k8s_client.V1NodeSystemInfo(
                        machine_id="virtual-kubelet-vast",
                        system_uuid="virtual-kubelet-vast",
                        boot_id="virtual-kubelet-vast",
                        kernel_version="5.4.0",
                        os_image="Ubuntu 22.04",
                        container_runtime_version="vastai://2.0.0",
                        kubelet_version="v1.28.0",
                        kube_proxy_version="v1.28.0", 
                        operating_system="linux",
                        architecture="amd64"
                    )
                )
            )
            
            self.v1.create_node(body=node)
            logger.info("Node registered successfully", node=self.node_name)
            
        except Exception as e:
            logger.error("Failed to register node", node=self.node_name, error=str(e))
    
    async def reconcile_existing_pods(self):
        """Reconcile existing pods on startup"""
        try:
            pods = self.v1.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={self.node_name}"
            ).items
            
            logger.info("Reconciling existing pods", count=len(pods))
            
            for pod in pods:
                if self._is_target_pod(pod):
                    logger.info("Reconciling pod", pod=pod.metadata.name)
                    await self.create_pod(pod)
                    
        except Exception as e:
            logger.error("Failed to reconcile existing pods", error=str(e))
    
    async def pod_watch_loop(self):
        """Watch for pod changes"""
        w = k8s_watch.Watch()
        
        while True:
            try:
                logger.info("Starting pod watch", node=self.node_name)
                
                stream = w.stream(
                    self.v1.list_pod_for_all_namespaces,
                    field_selector=f"spec.nodeName={self.node_name}",
                    timeout_seconds=60
                )
                
                for event in stream:
                    event_type = event.get("type")
                    pod = event.get("object")
                    
                    if not pod:
                        continue
                    
                    pod_name = pod.metadata.name
                    
                    logger.debug("Pod event", 
                               type=event_type, 
                               pod=pod_name,
                               phase=pod.status.phase if pod.status else None)
                    
                    if event_type == "ADDED":
                        await self.create_pod(pod)
                    elif event_type == "MODIFIED":
                        if (pod.metadata.deletion_timestamp or 
                            (pod.status and pod.status.phase in ("Succeeded", "Failed"))):
                            await self.delete_pod(pod)
                    elif event_type == "DELETED":
                        await self.delete_pod(pod)
                        
            except Exception as e:
                logger.error("Pod watch error", error=str(e))
                await asyncio.sleep(5)
    
    async def heartbeat_loop(self):
        """Update node status periodically"""
        while True:
            try:
                # Update node conditions
                try:
                    node = self.v1.read_node(name=self.node_name)
                    
                    # Update Ready condition
                    for condition in node.status.conditions:
                        if condition.type == "Ready":
                            condition.last_heartbeat_time = self._now()
                    
                    self.v1.patch_node_status(name=self.node_name, body=node)
                    
                except Exception as e:
                    logger.error("Heartbeat failed", error=str(e))
                
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error("Heartbeat loop error", error=str(e))
                await asyncio.sleep(15)

# Enhanced health check endpoints
async def healthz(request):
    return web.Response(text="ok")

async def readyz(request):
    return web.json_response({
        "status": "ready",
        "ssh_available": SSH_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    })

async def health_detailed(request):
    """Detailed health status"""
    vk = request.app['vk']
    
    status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "node_name": vk.node_name,
        "instances": {
            "active": len(vk.pod_instances),
            "max": vk.config.max_instances,
            "details": {
                name: {
                    "state": info["state"],
                    "id": info["id"],
                    "created": info["created"]
                }
                for name, info in vk.pod_instances.items()
            }
        },
        "metrics": {
            "error_counts": dict(vk.metrics.error_counts),
            "creation_times": len(vk.metrics.instance_creation_times),
            "api_latencies": len(vk.metrics.api_call_latencies)
        },
        "configuration": {
            "max_instances": vk.config.max_instances,
            "rate_limit_rpm": vk.config.rate_limit_rpm,
            "default_gpu": vk.config.default_gpu,
            "region": vk.config.region_preference
        }
    }
    
    return web.json_response(status)

async def metrics_endpoint(request):
    """Prometheus-style metrics"""
    vk = request.app['vk']
    
    metrics = []
    metrics.append(f'vast_active_instances {len(vk.pod_instances)}')
    metrics.append(f'vast_max_instances {vk.config.max_instances}')
    
    for error_type, count in vk.metrics.error_counts.items():
        metrics.append(f'vast_errors_total{{type="{error_type}"}} {count}')
    
    if vk.metrics.instance_creation_times:
        avg_creation = sum(m['duration'] for m in vk.metrics.instance_creation_times[-10:]) / min(10, len(vk.metrics.instance_creation_times))
        metrics.append(f'vast_instance_creation_duration_avg {avg_creation:.2f}')
    
    return web.Response(text='\n'.join(metrics), content_type='text/plain')

async def build_app(vk: VirtualKubelet) -> web.Application:
    """Build web application with enhanced endpoints"""
    app = web.Application()
    app['vk'] = vk
    
    app.router.add_get('/healthz', healthz)
    app.router.add_get('/readyz', readyz) 
    app.router.add_get('/health', health_detailed)
    app.router.add_get('/metrics', metrics_endpoint)
    
    return app

async def main():
    """Main application entry point"""
    
    # Load and validate configuration
    errors = config.validate()
    
    if errors:
        logger.error("Configuration validation failed", errors=errors)
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    
    logger.info("Starting Enhanced Virtual Kubelet for Vast.ai",
               node_name=config.node_name,
               max_instances=config.max_instances,
               rate_limit_rpm=config.rate_limit_rpm)
    
    # Initialize Virtual Kubelet
    vk = VirtualKubelet(config)
    
    # Register node
    await vk.register_node()
    
    # Start web server
    app = await build_app(vk)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10255)
    await site.start()
    
    logger.info("Web server started on port 10255")
    
    # Start background tasks
    tasks = [
        asyncio.create_task(vk.heartbeat_loop(), name="heartbeat"),
        asyncio.create_task(vk.reconcile_existing_pods(), name="reconcile"),
        asyncio.create_task(vk.pod_watch_loop(), name="pod_watch")
    ]
    
    try:
        logger.info("All services started, entering main loop")
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error("Fatal error in main loop", error=str(e))
    finally:
        logger.info("Shutting down...")
        
        # Cancel tasks
        for task in tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Cleanup web server
        await runner.cleanup()
        
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\nShutdown requested")
        exit(0)