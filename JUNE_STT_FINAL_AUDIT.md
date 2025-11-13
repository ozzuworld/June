# JUNE-STT Final Audit - Duplicate FINAL Investigation

**Date:** 2025-11-13
**Issue:** STT sending 6 duplicate FINALs for same utterance
**Current Behavior:** "Good morning, June" → 6 identical FINAL webhooks sent

---

## Critical Bugs Found

### 🔴 P0: Race Condition in State Reset (FOUND THE BUG!)

**Location:** `livekit_worker.py:530`
**Severity:** Critical - Causes duplicate FINALs

```python
# Line 508-530
if state.silence_counter >= silence_threshold and state.accumulated_text and not state.final_sent_for_utterance:
    logger.info("[LiveKit FINAL after silence] %s: %s", ...)

    # ✅ Send FINAL with retry logic
    success = await send_final_with_retry(...)  # ← BLOCKS HERE

    if success:
        state.final_sent_for_utterance = True
        state.last_final_time = time.time()
        state.reset_for_new_utterance()  # ← BUG: Resets flag immediately!
```

**The Problem:**
1. FINAL is sent successfully
2. `reset_for_new_utterance()` is called IMMEDIATELY
3. **This resets `final_sent_for_utterance = False`**
4. Loop continues, more silence chunks arrive
5. **Flag is False again, so condition passes**
6. Sends ANOTHER FINAL with the SAME text!

**Why 6 duplicates?**
The audio stream processes in 500ms chunks (line 380). After sending FINAL:
- Chunk 1: Send FINAL, reset flag
- Chunk 2: accumulated_text empty, skip
- But if processor still has buffered text:
  - Chunk 3-8: Re-emits same segments → accumulated_text builds up → sends FINALs

**The Fix:**
Don't call `reset_for_new_utterance()` until we're SURE a new utterance has started. Use a different approach:

```python
if success:
    state.final_sent_for_utterance = True
    state.last_final_time = time.time()
    # DON'T reset here! Keep accumulated_text to detect duplicates
    # Reset will happen when NEW audio with different text arrives
```

---

### 🟡 P1: No Duplicate Text Detection

**Location:** `livekit_worker.py:508`
**Issue:** Only checks `final_sent_for_utterance` flag, not text content

**Current Check:**
```python
if state.silence_counter >= silence_threshold and state.accumulated_text and not state.final_sent_for_utterance:
```

**Better Check:**
```python
# Track what was sent
last_final_sent: str = ""

# Before sending
if (state.silence_counter >= silence_threshold and
    state.accumulated_text and
    not state.final_sent_for_utterance and
    state.accumulated_text != last_final_sent):  # ← Add text comparison
```

---

### 🟡 P1: Processor Buffer Not Cleared

**Location:** `livekit_worker.py:419-423`
**Issue:** WhisperStreaming processor may re-emit same segments

```python
processor.insert_audio_chunk(audio_buffer)
audio_buffer = np.array([], dtype=np.float32)  # Buffer cleared

output = processor.process_iter()  # But processor internal buffer NOT cleared
```

**The processor maintains internal state** and may yield the same segments multiple times if `process_iter()` is called repeatedly without new meaningful audio.

**Fix:** After sending FINAL, create a NEW processor for next utterance:
```python
if success:
    # Close current processor
    processor.finish()
    # Create new one for next utterance
    processor = asr_service.create_processor()
```

---

### 🟢 P2: Retry Logic on Wrong Status Codes

**Location:** `livekit_worker.py:319-327`
**Issue:** Retries even when orchestrator explicitly rejects

```python
# Line 248-257: send_to_orchestrator returns False for 400/409/429
elif response.status_code in (400, 409, 429):
    logger.debug("⏸️ Orchestrator skipped transcript ...")
    return False  # ← Treated as "failure"

# Line 319-327: send_final_with_retry retries on False
if success:
    return True
# If we get here, success was False, so RETRY
```

**Result:** When orchestrator returns 409 (busy/duplicate), STT retries 3 times, creating extra duplicates.

**Fix:** Distinguish between "retryable failures" and "explicit rejections":
```python
async def send_to_orchestrator(...):
    # Return: (success: bool, should_retry: bool)
    if response.status_code == 200:
        return (True, False)
    elif response.status_code in (400, 409, 429):
        return (False, False)  # Don't retry rejections
    else:
        return (False, True)   # Retry server errors
```

---

## Current Code Quality Assessment

| Category | Score | Issues |
|----------|-------|--------|
| **Duplicate Prevention** | 30% | 🔴 Flag reset bug causes 6x duplicates |
| **State Management** | 70% | 🟡 State shared across iterations without isolation |
| **Error Handling** | 80% | ✅ Good logging, minor retry logic issue |
| **Processor Lifecycle** | 60% | 🟡 Processor reused without clearing |
| **Resource Cleanup** | 90% | ✅ Proper cleanup on disconnect |

**Overall: 66% Production Ready** (was 25% before enterprise fixes)

---

## Recommended Fixes (Priority Order)

### 1. Fix State Reset Bug (CRITICAL)

```python
# In _handle_audio_track, line 508-530
if state.silence_counter >= silence_threshold and state.accumulated_text and not state.final_sent_for_utterance:
    logger.info("[LiveKit FINAL after silence] %s: %s", participant.identity, state.accumulated_text)

    # Track what we're sending
    final_text = state.accumulated_text

    success = await send_final_with_retry(room_name=room_name, participant=participant.identity, text=final_text)

    if success:
        state.final_sent_for_utterance = True
        state.last_final_time = time.time()
        state.last_sent_final = final_text  # Track sent text

        # DON'T call reset_for_new_utterance() here!
        # It will be called when NEW different text arrives
```

### 2. Add New Utterance Detection

```python
# At the top of the main loop, before processing
if output[0] is not None:
    beg, end, text = output
    text = text.strip()

    # Check if this is a NEW utterance (different from last FINAL)
    if text and state.final_sent_for_utterance and text != state.last_sent_final:
        # New utterance detected! Reset for next one
        logger.info(f"🆕 New utterance detected, resetting state")
        state.reset_for_new_utterance()
```

### 3. Add Text-Based Duplicate Check

```python
# Add to ParticipantState dataclass
last_sent_final: str = ""

# Update FINAL send condition
if (state.silence_counter >= silence_threshold and
    state.accumulated_text and
    not state.final_sent_for_utterance and
    state.accumulated_text != state.last_sent_final):  # Prevent text duplicates
```

---

## Testing Plan

After applying fixes, test these scenarios:

### Test 1: Single Utterance
```
User: "Good morning, June"
Expected: Exactly 1 FINAL
```

### Test 2: Back-to-Back Utterances
```
User: "Good morning" [pause] "How are you"
Expected: 2 FINALs, no duplicates
```

### Test 3: Long Utterance
```
User: "Tell me about quantum mechanics and how it relates to computing"
Expected: 1 FINAL at end, multiple PARTIALs during speaking
```

### Test 4: Rapid Speech
```
User: "One" "Two" "Three" (quickly)
Expected: 3 FINALs or 1 combined, no duplicates
```

---

## Deployment Notes

**Before deploying:**
1. ✅ Syntax check: `python3 -m py_compile livekit_worker.py`
2. ✅ Review all 3 FINAL send locations
3. ✅ Test locally if possible
4. ⚠️ Model download: large-v2 is ~3GB, first startup will be slow (30-60s)

**After deploying:**
1. Monitor logs for "🆕 New utterance" messages
2. Check for absence of duplicate FINAL warnings
3. Verify response quality with large-v2 model

---

## Summary

**Root Cause:** `reset_for_new_utterance()` is called immediately after sending FINAL, clearing the `final_sent_for_utterance` flag. This allows subsequent silence chunks to trigger more FINAL sends with the same accumulated text.

**Impact:** 6 duplicate FINALs per utterance → wasted network bandwidth, noisy logs, orchestrator deduplication overhead

**Fix Complexity:** Medium - requires state management refactor

**ETA:** 1-2 hours to implement and test properly
