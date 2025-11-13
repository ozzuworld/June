# June-STT Service Enterprise Audit Report
**Date:** 2025-11-13
**Service:** june-stt (Speech-to-Text)
**Auditor:** Claude Code

---

## Executive Summary

The june-stt service is a critical component providing real-time speech-to-text for the voice AI assistant. While functionally working, it has **several critical issues** that prevent it from being enterprise-grade. The primary concern is **duplicate FINAL transcripts** causing poor user experience.

**Overall Grade: C+ (Functional but needs significant improvements)**

---

## 🔴 CRITICAL ISSUES (P0 - Must Fix Immediately)

### 1. Multiple FINAL Transcripts Sent Per Utterance
**Severity:** CRITICAL
**Location:** `livekit_worker.py:386-459`
**Impact:** User hears assistant respond multiple times to same input

**Problem:**
```python
# FINAL sent in 3 different places:
# 1. After silence detected (line 386-409)
if silence_counter >= silence_threshold and accumulated_text:
    await send_to_orchestrator(..., is_partial=False)  # FINAL #1

# 2. On track end with finish() (line 415-441)
output = processor.finish()
if output[0] is not None:
    await send_to_orchestrator(..., is_partial=False)  # FINAL #2

# 3. Fallback on track end (line 445-459)
if accumulated_text:
    await send_to_orchestrator(..., is_partial=False)  # FINAL #3
```

**Why it's critical:**
- Causes 3-6 duplicate responses from assistant
- Destroys conversation flow
- User confusion ("why is she repeating herself?")
- Already causing production issues (confirmed by user)

**Fix Required:**
- Add `final_sent` flag per participant/utterance
- Only send FINAL once
- Clear flag on new utterance

---

### 2. No Per-Participant State Management
**Severity:** CRITICAL
**Location:** `livekit_worker.py:233-463`
**Impact:** Multi-user conversations will interfere with each other

**Problem:**
All state is local to `_handle_audio_track()`:
```python
accumulated_text = ""  # Shared across all processing
last_segment_end = 0.0
silence_counter = 0
```

**Why it's critical:**
- Only works for single participant
- Multiple users in same room will corrupt each other's transcripts
- Not thread-safe
- Memory leaks (state never cleaned up)

**Fix Required:**
- Create `ParticipantState` class
- Store per participant: `Dict[str, ParticipantState]`
- Proper cleanup when participant leaves

---

### 3. No Delivery Guarantees for FINAL Transcripts
**Severity:** CRITICAL
**Location:** `livekit_worker.py:130-226`
**Impact:** Lost user input (unacceptable for voice assistant)

**Problem:**
```python
async def send_to_orchestrator(...):
    try:
        response = await client.post(webhook_url, ...)
        if response.status_code == 200:
            return True
        else:
            logger.debug("Orchestrator skipped...")  # ← Just logs and gives up!
            return False
```

**Why it's critical:**
- FINAL transcripts are user input - losing them is data loss
- No retry mechanism
- No queue/buffer for failed sends
- Silent failures

**Fix Required:**
- Implement retry with exponential backoff (3-5 attempts)
- Queue failed FINALs for later retry
- Alert/metrics on delivery failures
- Dead letter queue for permanent failures

---

## 🟠 HIGH PRIORITY ISSUES (P1 - Should Fix Soon)

### 4. Segment Concatenation Logic is Fragile
**Severity:** HIGH
**Location:** `livekit_worker.py:332-354`

**Problem:**
```python
is_new_segment = beg >= (last_segment_end - 0.3)  # Magic number, unclear behavior
```

**Issues:**
- Hardcoded 0.3s tolerance (why 0.3?)
- No documentation of edge cases
- Complex state machine hard to test
- Refinement vs concatenation logic unclear

**Fix:**
- Document expected behavior
- Add unit tests for edge cases
- Make tolerance configurable
- Simplify logic

---

### 5. No Metrics/Observability
**Severity:** HIGH
**Location:** Entire service

**Missing:**
- Latency metrics (time from audio → transcript)
- Error rates (failed sends, processing errors)
- Throughput (transcripts/second)
- Queue depths
- Model performance metrics
- Per-participant metrics

**Impact:**
- Can't detect degradation
- No SLO monitoring
- Debugging is reactive not proactive
- No capacity planning data

**Fix Required:**
- Add Prometheus metrics
- OpenTelemetry tracing
- Health check endpoint improvements
- Dashboard in Grafana

---

### 6. Error Handling is Incomplete
**Severity:** HIGH
**Location:** Multiple locations

**Problems:**
```python
except Exception as e:
    logger.error("Error in LiveKit audio handler: %s", e)
    # ← Then what? Continue? Crash? Retry?
```

**Issues:**
- Broad exception catching
- No recovery strategies
- No circuit breakers
- No graceful degradation

**Fix:**
- Specific exception handling
- Recovery procedures (reconnect, reset state)
- Circuit breaker for orchestrator calls
- Graceful degradation (best effort mode)

---

### 7. Configuration is Hardcoded
**Severity:** HIGH
**Location:** Throughout codebase

**Hardcoded values:**
```python
FINAL_COOLDOWN_SECONDS = 3.0  # livekit_worker.py:272
silence_threshold = 5  # livekit_worker.py:268
min_buffer_samples = int(16000 * 0.5)  # livekit_worker.py:256
model="base"  # main.py:173 - Hardcoded!
```

**Impact:**
- Can't tune without redeployment
- No A/B testing
- Can't adjust per-environment
- "base" model is low quality for production

**Fix:**
- Environment variables for all config
- Config validation
- Runtime config updates
- Use "large-v2" or "large-v3" for production

---

## 🟡 MEDIUM PRIORITY ISSUES (P2 - Nice to Have)

### 8. No Rate Limiting
**Location:** WebSocket endpoint, LiveKit worker
**Impact:** Potential DoS, resource exhaustion

**Fix:** Add rate limiting per participant

---

### 9. No Authentication/Authorization
**Location:** All endpoints
**Impact:** Anyone can use the service

**Fix:** Add API keys or JWT validation

---

### 10. Language Detection is Basic
**Location:** `livekit_worker.py:151-163`
**Impact:** May misdetect language

**Fix:** Use proper language detection library

---

### 11. No Graceful Shutdown
**Location:** `main.py`, `livekit_worker.py`
**Impact:** May lose in-flight transcripts on restart

**Fix:** Implement shutdown handlers

---

### 12. Memory Leak Potential
**Location:** `livekit_worker.py:259-273`
**Impact:** Long-running workers may accumulate state

**Variables that grow unbounded:**
- Participant tracking (no cleanup on disconnect)
- Error logs (no rotation)

**Fix:** Proper cleanup on participant disconnect

---

## ✅ POSITIVE ASPECTS

1. **Cooldown mechanism** (line 270-320) - Good idea to prevent stray partials
2. **Duplicate partial deduplication** (line 322-326) - Prevents some duplicates
3. **Proper audio buffering** (line 254-256) - Reduces processing overhead
4. **Health check endpoint** - Basic monitoring exists
5. **Error logging** - Good visibility into issues
6. **CORS configuration** - Proper web client support

---

## 📊 PERFORMANCE CONCERNS

### Current Configuration
```python
model="base"  # Fast but low accuracy
min_chunk_size=1.0  # 1 second chunks
```

### Issues:
1. **"base" model is not production-grade**
   - Lower accuracy than large-v2/v3
   - More word errors
   - Poor with accents/noise

2. **No model caching strategy**
   - Cold start ~5-10 seconds
   - No warm pool

3. **No horizontal scaling**
   - Single worker handles all rooms
   - No load balancing

---

## 🔧 RECOMMENDED FIXES (Priority Order)

### Immediate (This Week)

**1. Fix Multiple FINAL Sends (P0)**
```python
# Add to _handle_audio_track():
final_sent_for_utterance = False

# Before each FINAL send:
if not final_sent_for_utterance:
    await send_to_orchestrator(..., is_partial=False)
    final_sent_for_utterance = True

# Reset on new utterance:
# When accumulated_text is cleared
final_sent_for_utterance = False
```

**2. Add Retry Logic for FINAL (P0)**
```python
async def send_final_with_retry(
    room_name: str,
    participant: str,
    text: str,
    max_retries: int = 3
):
    for attempt in range(max_retries):
        success = await send_to_orchestrator(...)
        if success:
            return True
        await asyncio.sleep(2 ** attempt)  # Exponential backoff

    # After all retries failed
    logger.error(f"Failed to send FINAL after {max_retries} attempts: {text}")
    # TODO: Queue for later retry or alert
    return False
```

**3. Upgrade to large-v2 Model (P1)**
```python
config = ASRConfig(
    model="large-v2",  # ← Change from "base"
    language="en",
    task="transcribe",
    use_vac=True,
    min_chunk_size=1.0,
)
```

### Short Term (This Month)

**4. Add Per-Participant State Management (P0)**
```python
@dataclass
class ParticipantState:
    accumulated_text: str = ""
    last_segment_end: float = 0.0
    last_sent_partial: str = ""
    silence_counter: int = 0
    last_final_time: float = 0.0
    final_sent: bool = False

participant_states: Dict[str, ParticipantState] = {}
```

**5. Add Metrics (P1)**
```python
from prometheus_client import Counter, Histogram, Gauge

transcripts_sent = Counter('stt_transcripts_sent_total',
                          ['type', 'room'],
                          'Total transcripts sent')
processing_latency = Histogram('stt_processing_latency_seconds',
                              'Time to process audio')
active_participants = Gauge('stt_active_participants',
                           'Currently active participants')
```

**6. Configuration via Environment (P1)**
```python
import os

config = ASRConfig(
    model=os.getenv("WHISPER_MODEL", "large-v2"),
    language=os.getenv("WHISPER_LANGUAGE", "en"),
    min_chunk_size=float(os.getenv("MIN_CHUNK_SIZE", "1.0")),
)

FINAL_COOLDOWN = float(os.getenv("FINAL_COOLDOWN_SECONDS", "3.0"))
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "5"))
```

### Medium Term (Next Quarter)

**7. Add Circuit Breaker Pattern (P1)**
**8. Implement Health Metrics Endpoint (P1)**
**9. Add Rate Limiting (P2)**
**10. Graceful Shutdown (P2)**

---

## 🎯 ENTERPRISE READINESS CHECKLIST

| Category | Status | Priority |
|----------|--------|----------|
| ❌ No duplicate data sent | **FAIL** | P0 |
| ❌ Delivery guarantees | **FAIL** | P0 |
| ❌ Multi-tenant support | **FAIL** | P0 |
| ⚠️ Error handling | **PARTIAL** | P1 |
| ⚠️ Observability | **PARTIAL** | P1 |
| ❌ Configuration management | **FAIL** | P1 |
| ⚠️ Model quality | **LOW** | P1 |
| ❌ Metrics/monitoring | **FAIL** | P1 |
| ❌ Rate limiting | **MISSING** | P2 |
| ❌ Authentication | **MISSING** | P2 |
| ✅ Basic functionality | **PASS** | - |
| ✅ Logging | **PASS** | - |

**Current Score: 3/12 (25%)**
**Target for Enterprise: 10/12 (83%)**

---

## 💡 ARCHITECTURE RECOMMENDATIONS

### Current Architecture
```
User Audio → LiveKit → june-stt → Orchestrator → LLM
                         ↓ (single worker)
                    (no state management)
                    (no retry/queue)
```

### Recommended Architecture
```
User Audio → LiveKit → Load Balancer → june-stt (pool) → Message Queue → Orchestrator
                                          ↓                      ↓
                                    State Store          Dead Letter Queue
                                    (Redis)                   (Alerts)
                                          ↓
                                    Metrics/Tracing
                                    (Prometheus/Jaeger)
```

**Benefits:**
- Horizontal scaling
- State persistence
- Delivery guarantees
- Better observability
- Fault tolerance

---

## 🚀 DEPLOYMENT RECOMMENDATIONS

### Current Deployment Issues
1. No resource limits defined
2. No liveness/readiness probes
3. Single replica (no HA)
4. No auto-scaling

### Recommended Kubernetes Config
```yaml
resources:
  requests:
    memory: "4Gi"  # Whisper large-v2 needs ~3GB
    cpu: "2"
  limits:
    memory: "8Gi"
    cpu: "4"

replicas: 3  # For HA

livenessProbe:
  httpGet:
    path: /health
    port: 8001
  initialDelaySeconds: 60
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health
    port: 8001
  initialDelaySeconds: 30
  periodSeconds: 10
```

---

## 📝 CONCLUSION

### Must Fix Before Production
1. ✅ **Already fixed in orchestrator**: Duplicate handling (defensive)
2. ❌ **Must fix in STT**: Stop sending multiple FINALs (root cause)
3. ❌ **Must add**: Retry logic for FINAL delivery
4. ❌ **Must add**: Per-participant state management

### Should Fix for Enterprise
- Upgrade to large-v2 model
- Add comprehensive metrics
- Implement proper error recovery
- Make configuration dynamic
- Add horizontal scaling support

### Timeline Estimate
- **Critical fixes (P0):** 2-3 days
- **High priority (P1):** 1-2 weeks
- **Full enterprise-grade:** 4-6 weeks

---

**Next Steps:**
1. Review this audit with team
2. Prioritize fixes based on business impact
3. Create detailed implementation tickets
4. Set up staging environment for testing
5. Implement fixes incrementally with testing

**Questions? Issues? Let me know!**
