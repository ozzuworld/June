"""Minimal Prometheus metrics + log silencing"""
import time
from starlette.responses import Response
from prometheus_client import Counter, Histogram, Gauge, CONTENT_TYPE_LATEST, generate_latest

HTTP_REQUESTS_TOTAL = Counter("http_requests_total","HTTP requests",["method","path","status"])
HTTP_LATENCY = Histogram("http_request_latency_seconds","HTTP latency secs",["method","path"],[0.05,0.1,0.2,0.5,1,2,5])
CONVO_TTS_PHRASES = Counter("conversation_tts_phrases_total","Phrases published to TTS")
CIRCUIT_OPEN = Gauge("circuit_breaker_open","1=open,0=closed")

SILENCED = {"/healthz","/metrics"}

async def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

async def prometheus_http_middleware(request, call_next):
    path = request.url.path
    method = request.method
    start = time.time()
    resp = await call_next(request)
    label_path = path if path in SILENCED else path.split("?")[0]
    HTTP_REQUESTS_TOTAL.labels(method, label_path, str(resp.status_code)).inc()
    HTTP_LATENCY.labels(method, label_path).observe(time.time()-start)
    return resp
