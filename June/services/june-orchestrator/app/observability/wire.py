"""Wire Prometheus and silence noisy routes in app/main.py"""
from fastapi import FastAPI
from .observability.metrics import metrics_endpoint, prometheus_http_middleware


def wire_prometheus(app: FastAPI):
    @app.get("/metrics")
    async def metrics():
        return await metrics_endpoint()

    app.middleware("http")(prometheus_http_middleware)
