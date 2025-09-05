import os
from fastapi import FastAPI, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.routers import totp

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="June Auth (TOTP)")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
def ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return exc  # default 429 response

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Simple per-route limits for brute-force protection
app.include_router(totp.router, dependencies=[limiter.limit("10/minute")])
