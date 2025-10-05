"""
Administrative endpoints.

This module exposes a lightweight health check. It intentionally omits
detailed system metrics and memory introspection that were previously exposed,
reducing the attack surface and keeping the API straightforward.
"""

from fastapi import APIRouter

router = APIRouter(tags=["admin"])


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Return a simple health status for readiness probes."""
    return {"status": "ok"}