from typing import AsyncIterator
import httpx


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        yield client
