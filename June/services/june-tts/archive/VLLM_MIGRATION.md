# vLLM Migration Plan - Chatterbox TTS

**Date:** 2025-11-15
**Target:** 4-10x speed improvement over current Phase 1
**Current RTF:** 1.2-1.5 (Phase 1 with FP16)
**Expected RTF:** 0.3-0.75 (vLLM port)

---

## Overview

Migrate from `chatterbox-tts` (HuggingFace transformers) to `chatterbox-vllm` to achieve 4-10x speedup by eliminating CPU-GPU sync bottlenecks.

### Performance Expectations

**Benchmarks (RTX 3090):**
- Input: 6.6k words → 40 minutes audio
- vLLM total time: 87 seconds
- Breakdown: 13.3s T3 generation, 60.8s S3Gen waveform
- **Speedup: 3-4x over original implementation**

**With batching:** 10x+ throughput improvement

---

## Key Changes Required

### 1. Dependencies

**Remove:**
```
chatterbox-tts>=0.1.0
```

**Add:**
```
# vLLM port from GitHub (requires vLLM 0.9.2)
git+https://github.com/randombk/chatterbox-vllm.git
vllm==0.9.2
```

### 2. API Changes

| Aspect | Original Chatterbox | vLLM Port |
|--------|-------------------|-----------|
| **Import** | `from chatterbox.mtl_tts import ChatterboxMultilingualTTS` | `from chatterbox_vllm.tts import ChatterboxTTS` |
| **Init** | `ChatterboxMultilingualTTS.from_pretrained(device=DEVICE)` | `ChatterboxTTS.from_pretrained(gpu_memory_utilization=0.4, max_model_len=1000)` |
| **Generate** | `model.generate(text, language_id="en", ...)` | `model.generate([text], audio_prompt_path=..., exaggeration=...)` |
| **CFG Weight** | `cfg_weight` parameter | `CHATTERBOX_CFG_SCALE` env var |
| **Output** | Returns tensor directly | Returns list of tensors |
| **Batching** | Manual | Automatic (pass list) |

### 3. Parameter Mapping

| Original | vLLM Port | Notes |
|----------|-----------|-------|
| `text` | `prompts` (list) | vLLM expects list of strings |
| `audio_prompt_path` | `audio_prompt_path` | Same (supports MP3) |
| `exaggeration` | `exaggeration` | Same (0.0-1.0) |
| `cfg_weight` | `CHATTERBOX_CFG_SCALE` env | Global setting, not per-request |
| `temperature` | N/A | Not exposed in vLLM port |
| `language_id` | ⚠️ Limited support | Early implementation, quality degradation |

---

## Migration Steps

### Phase 1: Preparation

1. ✅ Research vLLM API and compatibility
2. 🔄 Document API differences
3. 🔄 Create migration plan
4. 🔄 Identify potential issues

### Phase 2: Dockerfile Updates

1. Install vLLM 0.9.2
2. Install chatterbox-vllm from GitHub
3. Update Python dependencies
4. Test build

### Phase 3: Code Migration

1. Update imports
2. Modify model initialization
3. Adapt generate() function
4. Handle CFG via environment variable
5. Update response handling (list → single tensor)
6. Add batching support for multiple requests

### Phase 4: Testing

1. Test single request generation
2. Test voice cloning
3. Test batching performance
4. Measure RTF improvement
5. Validate audio quality

### Phase 5: Documentation

1. Update PHASE1_OPTIMIZATIONS.md → VLLM_OPTIMIZATIONS.md
2. Document API changes
3. Update health endpoint
4. Add performance benchmarks

---

## Implementation Details

### Model Initialization

**Before:**
```python
if USE_MULTILINGUAL:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    model = ChatterboxMultilingualTTS.from_pretrained(device=DEVICE)
else:
    from chatterbox.tts import ChatterboxTTS
    model = ChatterboxTTS.from_pretrained(device=DEVICE)
```

**After:**
```python
from chatterbox_vllm.tts import ChatterboxTTS

model = ChatterboxTTS.from_pretrained(
    gpu_memory_utilization=0.6,  # Adjust based on GPU VRAM
    max_model_len=1000,          # Max tokens per request
    enforce_eager=True,          # Faster startup for single requests
)
```

### Generation

**Before:**
```python
wav = model.generate(
    text,
    audio_prompt_path=audio_prompt_path,
    exaggeration=exaggeration,
    cfg_weight=cfg_weight,
    temperature=temperature,
    language_id=language_id
)
```

**After:**
```python
# vLLM expects list of prompts
prompts = [text]

# CFG controlled via env var (set at startup)
os.environ["CHATTERBOX_CFG_SCALE"] = str(cfg_weight)

audios = model.generate(
    prompts,
    audio_prompt_path=audio_prompt_path,
    exaggeration=exaggeration,
)

# Extract single audio from list
wav = audios[0]
```

### Batching Support

**New capability with vLLM:**
```python
# Process multiple requests simultaneously
prompts = [request1.text, request2.text, request3.text]

audios = model.generate(
    prompts,
    audio_prompt_path=shared_voice_path,
    exaggeration=0.5,
)

# Returns list of audio tensors
for audio, request in zip(audios, requests):
    # Handle each result
    pass
```

---

## Environment Variables

**New vLLM-specific:**
```bash
# CFG scale (replaces per-request cfg_weight)
CHATTERBOX_CFG_SCALE=0.5

# GPU memory allocation
VLLM_GPU_MEMORY_UTILIZATION=0.6

# Max tokens per request
VLLM_MAX_MODEL_LEN=1000

# Disable CUDA graphs for faster startup
VLLM_ENFORCE_EAGER=1
```

**Existing (keep):**
```bash
USE_FP16=1  # May not apply to vLLM (handles internally)
USE_MULTILINGUAL=1  # May have limited support in vLLM
```

---

## Known Limitations

### 1. Multilingual Support
- ⚠️ Early implementation in vLLM port
- ⚠️ Quality degradation due to missing Alignment Stream Analyzer
- ⚠️ Learned speech positional embeddings not implemented
- **Decision:** May need to stick with English-only initially

### 2. API Instability
- ⚠️ Uses vLLM internal APIs
- ⚠️ APIs subject to change before v1.0
- ⚠️ Requires vLLM 0.9.2 specifically
- **Risk:** May break with vLLM updates

### 3. Parameter Loss
- ❌ `temperature` parameter not exposed
- ❌ Per-request CFG control (now global)
- ❌ Language switching flexibility
- **Impact:** Less fine-grained control per request

### 4. Memory Estimation
- ⚠️ vLLM may underestimate memory due to CFG workaround
- **Risk:** Potential OOM errors
- **Mitigation:** Conservative `gpu_memory_utilization` setting

---

## Rollback Plan

If vLLM port has issues:

1. Git revert to Phase 1 implementation
2. Keep Phase 1 optimizations (FP16, parameters)
3. Explore streaming instead (davidbrowne17/chatterbox-streaming)

```bash
# Rollback command
git revert <vllm-migration-commit>
git push origin claude/optimize-chatterbox-tts-01Q12xMYjEz3ubBrKkxo9Wa1
```

---

## Testing Checklist

### Functional Tests
- [ ] Service starts successfully
- [ ] Model loads without errors
- [ ] Single text synthesis works
- [ ] Voice cloning works
- [ ] Audio quality is acceptable
- [ ] LiveKit streaming works
- [ ] Health endpoint reports correctly

### Performance Tests
- [ ] Measure RTF for single request
- [ ] Measure RTF with batching (2-4 requests)
- [ ] Compare against Phase 1 baseline
- [ ] Monitor GPU memory usage
- [ ] Test concurrent request handling

### Expected Results
- [ ] RTF < 1.0 (faster than real-time)
- [ ] RTF 0.3-0.75 (4-10x improvement)
- [ ] GPU memory usage < 80%
- [ ] No quality degradation vs original

---

## Success Criteria

### Minimum (Keep vLLM)
- ✅ RTF < 1.0
- ✅ 2x improvement over Phase 1
- ✅ No significant quality loss
- ✅ Stable under normal load

### Target (Optimal)
- ✅ RTF 0.3-0.75
- ✅ 4-10x improvement
- ✅ Batching works for concurrent requests
- ✅ Production-ready stability

### Deal-breaker (Rollback)
- ❌ RTF > Phase 1 (slower)
- ❌ Significant quality degradation
- ❌ Frequent crashes/errors
- ❌ Memory issues

---

## Timeline

**Estimated:** 1-2 days

| Phase | Time | Status |
|-------|------|--------|
| Research & Planning | 2-3 hours | ✅ Complete |
| Dockerfile updates | 1-2 hours | 🔄 In progress |
| Code migration | 2-3 hours | ⏳ Pending |
| Testing & validation | 2-4 hours | ⏳ Pending |
| Documentation | 1-2 hours | ⏳ Pending |
| **Total** | **8-14 hours** | **~1-2 days** |

---

## Next Steps

1. **Update Dockerfile** with vLLM dependencies
2. **Update requirements.txt** with vLLM package
3. **Migrate main.py** to use vLLM API
4. **Test locally** (if possible)
5. **Deploy and benchmark**
6. **Document results**

---

## Resources

- **vLLM Port:** https://github.com/randombk/chatterbox-vllm
- **Original Chatterbox:** https://github.com/resemble-ai/chatterbox
- **vLLM Docs:** https://docs.vllm.ai/
- **Performance Discussion:** https://github.com/resemble-ai/chatterbox/issues/193

---

**Status:** 🔄 Ready to begin migration
**Risk Level:** Medium (API instability, multilingual limitations)
**Reward:** High (4-10x speedup potential)
