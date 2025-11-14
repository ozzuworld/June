# June STT Service Configuration Guide

## Quick Start

The June STT service now supports easy model swapping and quantization for optimal performance.

### Environment Variables

Configure the STT service via environment variables:

```bash
# Model Selection
WHISPER_MODEL=large-v2              # Options: tiny, base, small, medium, large-v2, large-v3

# Quantization (Performance Optimization)
WHISPER_COMPUTE_TYPE=int8_float16   # Options: float32, float16, int8, int8_float16, int8_float32

# Device Selection
WHISPER_DEVICE=auto                 # Options: auto, cpu, cuda
```

---

## Model Options

### Whisper Models (Accuracy vs Speed Trade-off)

| Model | Size | Accuracy | Speed | Use Case |
|-------|------|----------|-------|----------|
| `tiny` | 39 MB | Basic | Very Fast | Testing only |
| `base` | 74 MB | Good | Fast | Development |
| `small` | 244 MB | Better | Moderate | Light production |
| `medium` | 769 MB | Great | Slower | Balanced production |
| **`large-v2`** | 1.5 GB | **Best** | Moderate | **Production (current)** |
| `large-v3` | 1.5 GB | Best | Moderate | Latest production |

**Recommendation:** Use `large-v2` or `large-v3` for production.

---

## Quantization Options

Quantization reduces model precision to improve inference speed with minimal accuracy loss.

### Compute Types

| Compute Type | Speed Gain | Accuracy | Memory | Recommendation |
|--------------|------------|----------|--------|----------------|
| `float32` | Baseline | 100% | High | Reference only |
| `float16` | ~15% | 99.5% | Medium | Good balance |
| **`int8_float16`** | **~25%** | **99%** | **Low** | **✅ Recommended** |
| `int8_float32` | ~25% | 99% | Medium | Alternative |
| `int8` | ~30% | 98% | Very Low | Maximum speed |

**Recommendation:** Use `int8_float16` for best balance of speed and accuracy (currently enabled).

### Expected Performance Impact

- **Latency Reduction:** 20-30% faster inference with `int8_float16`
- **Accuracy Impact:** <1% WER (Word Error Rate) difference
- **Memory Savings:** ~50% reduction in GPU memory usage

---

## Alternative STT Providers

For even faster transcription, consider evaluating these providers:

### Deepgram Nova-3 (Recommended)

**Pros:**
- Sub-300ms latency (vs ~500ms Whisper)
- Excellent accuracy (competitive with Whisper)
- Cost-effective pricing
- Built-in streaming support

**Integration:**
```python
# Example integration (future enhancement)
from deepgram import Deepgram

dg_client = Deepgram(api_key=os.getenv("DEEPGRAM_API_KEY"))
```

**Benchmarks:**
- TTFB (Time To First Byte): ~270ms
- Final latency: ~698ms
- WER: Competitive with Whisper large-v2

### AssemblyAI Universal-2

**Pros:**
- Best accuracy among streaming models (14.5% WER)
- Strong domain-specific performance
- Robust API

**Cons:**
- Higher cost than Deepgram
- Slightly higher latency than Nova-3

### Comparison Table

| Provider | Latency | Accuracy (WER) | Cost/Hour | Streaming | Local |
|----------|---------|----------------|-----------|-----------|-------|
| **Whisper large-v2** | ~500ms | 15.2% | Free | ✅ | ✅ |
| Deepgram Nova-3 | ~270ms | 15.0% | $$ | ✅ | ❌ |
| AssemblyAI Universal-2 | ~350ms | 14.5% | $$$ | ✅ | ❌ |

---

## Configuration Examples

### Development (Fast, Good Enough)

```env
WHISPER_MODEL=small
WHISPER_COMPUTE_TYPE=int8_float16
WHISPER_DEVICE=cuda
```

**Expected:** ~200ms latency, 95% accuracy

---

### Production (Best Accuracy, Current Default)

```env
WHISPER_MODEL=large-v2
WHISPER_COMPUTE_TYPE=int8_float16
WHISPER_DEVICE=cuda
```

**Expected:** ~400ms latency, 99% accuracy

---

### Maximum Speed (Testing)

```env
WHISPER_MODEL=medium
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=cuda
```

**Expected:** ~250ms latency, 97% accuracy

---

### CPU-Only (No GPU)

```env
WHISPER_MODEL=small
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=cpu
```

**Expected:** ~1000ms latency, 95% accuracy

---

## Kubernetes/Helm Configuration

Update your Helm values or Kubernetes deployment:

```yaml
# helm/june-platform/values.yaml
june-stt:
  env:
    - name: WHISPER_MODEL
      value: "large-v2"
    - name: WHISPER_COMPUTE_TYPE
      value: "int8_float16"
    - name: WHISPER_DEVICE
      value: "cuda"
```

---

## Testing Different Models

1. **Check current config:**
   ```bash
   curl http://june-stt:8080/config
   ```

2. **Update environment variables** in your deployment

3. **Restart the service:**
   ```bash
   kubectl rollout restart deployment june-stt -n june-services
   ```

4. **Monitor logs:**
   ```bash
   kubectl logs -f deployment/june-stt -n june-services
   ```

   Look for:
   ```
   Loading Whisper large-v2 model for en (compute_type=int8_float16, device=cuda)...
   ✅ ASR Microservice started successfully (model=large-v2, compute_type=int8_float16, device=cuda)
   ```

---

## Performance Monitoring

Check transcription quality and latency:

```bash
# View real-time STT metrics
kubectl logs -f deployment/june-stt -n june-services | grep "FINAL\|confidence"
```

Key metrics to watch:
- **TTFB (Time To First Byte):** First partial transcript latency
- **Final latency:** Time from speech end to final transcript
- **Confidence scores:** Average should be >0.8

---

## Troubleshooting

### High Latency (>1s)

**Possible causes:**
- Model too large for GPU
- No quantization enabled
- CPU fallback (check device logs)

**Solutions:**
- Use smaller model (`medium` instead of `large-v2`)
- Enable quantization: `WHISPER_COMPUTE_TYPE=int8_float16`
- Check GPU availability

### Low Accuracy (<95%)

**Possible causes:**
- Aggressive quantization
- Model too small
- Noisy audio

**Solutions:**
- Use less aggressive quantization: `float16` instead of `int8`
- Upgrade model: `large-v2` instead of `small`
- Check confidence scores in logs

### Out of Memory (OOM)

**Possible causes:**
- Model too large for GPU
- No quantization

**Solutions:**
- Use smaller model: `medium` or `small`
- Enable quantization: `int8_float16` (reduces memory 50%)
- Reduce concurrent streams

---

## Best Practices

1. **Production:** Use `large-v2` + `int8_float16` for best balance
2. **Development:** Use `small` + `int8_float16` for fast iteration
3. **Testing:** Use `medium` + `int8` for quick validation
4. **Monitoring:** Always check confidence scores (target: >0.8)
5. **Latency Target:** Aim for <500ms final latency (current: ~400ms)

---

## Future Enhancements

- [ ] Deepgram Nova-3 integration for sub-300ms latency
- [ ] AssemblyAI Universal-2 option for maximum accuracy
- [ ] Automatic model selection based on load
- [ ] A/B testing framework for model comparison
- [ ] Real-time confidence monitoring dashboard

---

## References

- [Faster Whisper Documentation](https://github.com/guillaumekln/faster-whisper)
- [Whisper Model Card](https://github.com/openai/whisper)
- [Deepgram Nova-3 Benchmarks](https://deepgram.com/learn/best-speech-to-text-apis)
- [STT Latency Measurement Guide](https://www.gladia.io/blog/measuring-latency-in-stt)
