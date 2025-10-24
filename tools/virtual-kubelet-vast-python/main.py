#!/usr/bin/env python3
# Update to use compose-based multi-container runtime on Vast.ai instance
# Replaces single-image onstart with a generated compose file using prebuilt images.

import asyncio
import base64
import json
import os
import re
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import structlog
from kubernetes import client as k8s_client

from .runtime_templates import COMPOSE_YAML, BASH_ONSTART

logger = structlog.get_logger()

# ... keep existing classes and methods ...

class VastAIClient:
    # ... existing methods ...
    async def buy_instance(self, ask_id: int, ann: Dict[str,str], pod) -> Optional[Dict[str, Any]]:
        image = os.getenv("VAST_START_IMAGE") or ann.get("vast.ai/start-image", "ubuntu:22.04")
        disk_str = ann.get("vast.ai/disk", "50")
        try:
            disk_gb = float(re.match(r"(\d+(?:\.\d+)?)", disk_str).group(1))
        except Exception:
            disk_gb = 50.0

        # Gather env for compose runtime
        tts_port = ann.get("june.tts/port", "8000")
        stt_port = ann.get("june.stt/port", "8001")

        # Build Tailscale env (from Pod env/secret)
        tailscale_env = self._build_tailscale_env_string(pod)
        tailscale_key = ""
        if tailscale_env:
            # Extract TAILSCALE_AUTH_KEY=value from env string if present
            m = re.search(r"-e TAILSCALE_AUTH_KEY=([^\s]+)", tailscale_env)
            if m:
                tailscale_key = m.group(1)

        # Render onstart script with embedded compose & .env
        compose_b64 = base64.b64encode(COMPOSE_YAML.encode()).decode()
        onstart_script = BASH_ONSTART.format(
            compose=COMPOSE_YAML,
            tailscale_auth=tailscale_key,
            tts_port=tts_port,
            stt_port=stt_port,
        )

        # Build create instance args
        args = [
            "create","instance",str(ask_id),"--raw",
            "--image", image,
            "--disk", str(int(disk_gb)),
            "--onstart-cmd", onstart_script,
        ]

        logger.info("Creating Vast.ai instance with compose-based runtime", image=image, tts_port=tts_port, stt_port=stt_port)
        res = await self._run(args)
        data = res.get("data")
        if isinstance(data, str) and data.isdigit():
            return {"new_contract": int(data)}
        if isinstance(data, dict) and "new_contract" in data:
            return data
        return None
