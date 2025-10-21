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
from kubernetes import client as k8s_client, config as k8s_config, watch as k8s_watch
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
        # Check common locations
        paths = [
            shutil.which("vastai"),
            "/usr/local/bin/vastai",
            "/app/vastai",
        ]
        for path in paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                logger.info("Found vastai CLI", path=path)
                return path
        logger.warning("vastai CLI not found, will fail")
        return None
    
    def _setup_api_key(self):
        """Set up API key for CLI"""
        if self.api_key:
            # Write API key to expected location
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
        """Convert GPU name to CLI format (spaces -> underscores)"""
        return gpu_name.replace(" ", "_")
    
    def _build_search_query(self, gpu_type: str, max_price: float, region: Optional[str] = None) -> str:
        """Build vastai CLI search query string"""
        gpu_cli = self._gpu_name_to_cli_format(gpu_type)
        query_parts = [
            "rentable=True",
            "verified=True", 
            "rented=False",
            f"gpu_name={gpu_cli}",
            f"dph <= {max_price}",
            "reliability >= 0.90",
            "inet_down >= 100"
        ]
        
        if region:
            # Map common region names to CLI format
            region_map = {
                "North America": "geolocation=US",
                "US": "geolocation=US", 
                "United States": "geolocation=US",
                "Europe": "geolocation=DE",  # Use DE as EU representative
                "Asia": "geolocation=JP",    # Use JP as Asia representative
            }
            if region in region_map:
                query_parts.append(region_map[region])
        
        return " ".join(query_parts)
    
    async def _run_cli_command(self, args: List[str]) -> Dict[str, Any]:
        """Run vastai CLI command safely with rate limiting"""
        if not self.cli_path:
            raise RuntimeError("vastai CLI not available")
        
        await _respect_global_rate_limit()  # Enforce rate limiting
        
        cmd = [self.cli_path] + args
        try:
            logger.debug("Running CLI command", cmd=cmd)
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error("CLI command failed", cmd=cmd, error=error_msg, returncode=result.returncode)
                
                # Check for rate limiting in CLI output
                if "rate" in error_msg.lower() or "too many" in error_msg.lower():
                    logger.warning("CLI rate limited, backing off")
                    await asyncio.sleep(min(BACKOFF_MAX, BACKOFF_INITIAL * 2))
                
                return {"error": error_msg, "returncode": result.returncode}
            
            output = stdout.decode().strip()
            if not output:
                return {"data": []}
            
            # Try to parse JSON output
            try:
                if output.startswith("[") or output.startswith("{"):
                    return {"data": json.loads(output)}
                else:
                    # Non-JSON output (like instance ID)
                    return {"data": output}
            except json.JSONDecodeError:
                # Fallback for non-JSON responses
                return {"data": output}
                
        except Exception as e:
            logger.error("CLI command exception", cmd=cmd, error=str(e))
            return {"error": str(e)}
    
    async def search_offers(self, gpu_type: str = "RTX 4060", max_price: float = 0.50, region: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for offers using vastai CLI"""
        query = self._build_search_query(gpu_type, max_price, region)
        
        # Use CLI search command with raw JSON output
        result = await self._run_cli_command([
            "search", "offers", 
            "--raw",  # JSON output
            "--no-default",  # No default filters
            query,
            "-o", "dph-"  # Sort by price (lowest first)
        ])
        
        if "error" in result:
            logger.error("CLI search failed", gpu_type=gpu_type, error=result["error"])
            return []
        
        offers = result.get("data", [])
        if isinstance(offers, list):
            logger.info("CLI search success", gpu_type=gpu_type, offer_count=len(offers))
            return offers
        else:
            logger.warning("CLI search returned non-list", gpu_type=gpu_type, data_type=type(offers))
            return []
    
    async def buy_instance(self, ask_id: int, pod_annotations: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Buy instance using vastai CLI"""
        image = pod_annotations.get("vast.ai/image", "pytorch/pytorch:2.2.0-cuda12.1-cudnn8-devel")
        disk_str = pod_annotations.get("vast.ai/disk", "50")
        
        # Parse disk size
        try:
            disk_gb = float(re.match(r'(\d+(?:\.\d+)?)', disk_str).group(1))
        except (AttributeError, ValueError):
            disk_gb = 50.0
        
        # Build create command
        cmd_args = [
            "create", "instance", 
            str(ask_id),
            "--raw",  # JSON output
            "--image", image,
            "--disk", str(int(disk_gb))
        ]
        
        # Add optional parameters
        if "vast.ai/onstart-cmd" in pod_annotations:
            cmd_args.extend(["--onstart", pod_annotations["vast.ai/onstart-cmd"]])
        
        if "vast.ai/env" in pod_annotations:
            cmd_args.extend(["--env", pod_annotations["vast.ai/env"]])
        
        result = await self._run_cli_command(cmd_args)
        
        if "error" in result:
            logger.error("CLI create instance failed", ask_id=ask_id, error=result["error"])
            return None
        
        # CLI returns instance ID or JSON with instance info
        data = result.get("data")
        if isinstance(data, str) and data.isdigit():
            instance_id = int(data)
            logger.info("Instance creation initiated via CLI", ask_id=ask_id, instance_id=instance_id)
            return {"new_contract": instance_id}
        elif isinstance(data, dict) and "new_contract" in data:
            logger.info("Instance creation initiated via CLI", ask_id=ask_id, instance_id=data["new_contract"])
            return data
        else:
            logger.error("CLI create returned unexpected format", ask_id=ask_id, data=data)
            return None
    
    async def poll_instance_ready(self, instance_id: int, timeout_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """Poll instance status using vastai CLI"""
        start_time = time.time()
        
        while (time.time() - start_time) < timeout_seconds:
            result = await self._run_cli_command([
                "show", "instance", str(instance_id), "--raw"
            ])
            
            if "error" in result:
                logger.warning("Error polling instance via CLI", instance_id=instance_id, error=result["error"])
                await asyncio.sleep(10)
                continue
            
            data = result.get("data")
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
        """Delete instance using vastai CLI"""
        result = await self._run_cli_command([
            "destroy", "instance", str(instance_id)
        ])
        
        if "error" in result:
            # 404-like errors are OK (instance already gone)
            error = result["error"].lower()
            if "not found" in error or "does not exist" in error:
                logger.info("Instance already deleted via CLI", instance_id=instance_id)
                return True
            
            logger.error("Failed to delete instance via CLI", instance_id=instance_id, error=result["error"])
            return False
        
        logger.info("Instance deleted via CLI", instance_id=instance_id)
        return True


# ... rest of file remains unchanged ...
