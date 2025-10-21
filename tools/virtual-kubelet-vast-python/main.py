#!/usr/bin/env python3
from __future__ import annotations

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

# ... rest of file unchanged, ensure Optional is imported above ...
