# CosyVoice v1 to CosyVoice2 Migration Guide

## Overview

This document explains the critical API differences between CosyVoice v1 (300M-SFT) and CosyVoice2 (0.5B) and why the previous code was failing.

## The Problem

### Error You Were Seeing

```
june-tts | KeyError: '英文女'
june-tts | File "/opt/CosyVoice/cosyvoice/cli/frontend.py", line 153, in frontend_sft
june-tts |     embedding = self.spk2info[spk_id]['embedding']
```

### Root Cause

The code was calling `cosyvoice_model.inference_sft(text, speaker, stream=stream)` with speaker ID `"英文女"` (English Female), but **CosyVoice2 does NOT support the `inference_sft()` method or predefined speaker IDs**.

## Key API Differences

### CosyVoice v1 (300M-SFT) - OLD

**Supported Methods:**
- `inference_sft(text, speaker_id, stream)` - Uses predefined speakers

**Predefined Speaker IDs:**
- `"英文女"` - English Female
- `"英文男"` - English Male  
- `"中文女"` - Chinese Female
- `"中文男"` - Chinese Male
- `"日语男"` - Japanese Male
- `"粤语女"` - Cantonese Female
- `"韩语女"` - Korean Female

**Usage:**
```python
# CosyVoice v1
for output in model.inference_sft("Hello world", "英文女", stream=True):
    audio = output['tts_speech']
```

### CosyVoice2 (0.5B) - NEW

**Supported Methods:**
1. `inference_zero_shot(text, prompt_text, prompt_speech, stream)` - Voice cloning from reference audio
2. `inference_cross_lingual(text, prompt_speech, stream)` - Cross-language synthesis with tags
3. `inference_instruct2(text, instruct_text, prompt_speech, stream)` - Instruction-based synthesis

**NO Predefined Speakers:** CosyVoice2 does NOT have speaker IDs. All synthesis requires reference audio.

**Usage:**
```python
# CosyVoice2 - Zero-shot
prompt_audio = load_wav("reference.wav", 16000)
prompt_text = "This is the reference audio transcript"

for output in model.inference_zero_shot(
    "Hello world",
    prompt_text, 
    prompt_audio,
    stream=True
):
    audio = output['tts_speech']

# CosyVoice2 - Cross-lingual with language tags
for output in model.inference_cross_lingual(
    "<|en|>Hello<|zh|>你好<|en|>World",
    prompt_audio,
    stream=True
):
    audio = output['tts_speech']
```

## What Was Changed

### 1. `June/services/june-tts/main.py`

**Before:**
```python
# ❌ BROKEN - inference_sft doesn't exist in CosyVoice2
for output in cosyvoice_model.inference_sft(text, speaker, stream=stream):
    audio_chunks.append(output['tts_speech'])
```

**After:**
```python
# ✅ WORKS - Uses zero-shot with reference audio
for output in cosyvoice_model.inference_zero_shot(
    text, 
    prompt_text, 
    prompt_speech, 
    stream=stream
):
    audio_chunks.append(output['tts_speech'])
```

### 2. `June/services/june-orchestrator/app/services/tts_service.py`

**Before:**
```python
payload = {
    "speaker_id": "英文女",  # ❌ Not supported in v2
}
```

**After:**
```python
payload = {
    "language": "en",  # ✅ Language code instead
}
```

### 3. `June/services/june-orchestrator/app/voice_registry.py`

**Before:**
```python
COSYVOICE2_SPEAKERS = {
    "en_female": "英文女",  # ❌ These don't exist in v2
    "zh_female": "中文女",
}
```

**After:**
```python
SUPPORTED_LANGUAGES = {
    "en": "English",  # ✅ Language codes
    "zh": "Chinese",
}
```

### 4. `June/services/june-tts/Dockerfile`

**Before:**
```dockerfile
# ❌ Downloads spk2info.pt from CosyVoice-300M-SFT (incompatible)
RUN python3 << 'PYTHON_SCRIPT'
    snapshot_download('iic/CosyVoice-300M-SFT', ...)
    shutil.copy('spk2info.pt', 'CosyVoice2-0.5B/spk2info.pt')
PYTHON_SCRIPT
```

**After:**
```dockerfile
# ✅ Downloads reference audio for zero-shot synthesis
RUN wget -O asset/zero_shot_prompt.wav \
    https://github.com/FunAudioLLM/CosyVoice/raw/main/asset/zero_shot_prompt.wav
```

## Reference Audio Requirement

CosyVoice2 **requires reference audio** for synthesis. The service now loads default reference audio at startup:

### Default Reference Files

Place these in `/opt/CosyVoice/asset/`:

1. **`zero_shot_prompt.wav`** - English reference
2. **`cross_lingual_prompt.wav`** - Chinese reference

These files are automatically downloaded from the CosyVoice repository during Docker build.

### Custom Reference Audio

For custom voices, you can:

1. **Use the `/tts/zero-shot` endpoint** with your own reference audio
2. **Use the `/tts/cross-lingual` endpoint** for multilingual synthesis
3. **Use the `/tts/instruct` endpoint** for instruction-based control

## API Contract Changes

### Request Model

**Before:**
```python
class LiveKitPublishRequest(BaseModel):
    speaker: str = Field("英文女", description="Speaker name")
```

**After:**
```python
class TTSRequest(BaseModel):
    language: str = Field("en", description="Language code")
```

### Response Model

**Before:**
```python
{
    "speaker": "英文女",
    "available_speakers": ["英文女", "中文女", ...]
}
```

**After:**
```python
{
    "language": "en",
    "model_type": "CosyVoice2-0.5B",
    "supported_methods": ["zero_shot", "cross_lingual", "instruct2"]
}
```

## Testing the Fixed Service

### 1. Rebuild the Docker Image

```bash
docker build -t june-tts:latest ./June/services/june-tts/
```

### 2. Test the Main Endpoint

```bash
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is a test",
    "room_name": "test-room",
    "language": "en",
    "stream": true
  }'
```

### 3. Check Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "livekit_connected": true,
  "model_type": "CosyVoice2-0.5B",
  "supported_methods": ["zero_shot", "cross_lingual", "instruct2"]
}
```

## Common Issues

### Issue: "No reference audio available"

**Cause:** Reference audio files not found in `/opt/CosyVoice/asset/`

**Solution:**
```bash
# Download reference audio manually
cd /opt/CosyVoice/asset/
wget https://github.com/FunAudioLLM/CosyVoice/raw/main/asset/zero_shot_prompt.wav
wget https://github.com/FunAudioLLM/CosyVoice/raw/main/asset/cross_lingual_prompt.wav
```

### Issue: Old code still using speaker IDs

**Cause:** Legacy code calling with `speaker_id` parameter

**Solution:** Update to use `language` parameter:
```python
# Before
await tts.publish_to_room(text="Hello", speaker_id="英文女")

# After  
await tts.publish_to_room(text="Hello", language="en")
```

## Summary

| Feature | CosyVoice v1 | CosyVoice2 |
|---------|--------------|------------|
| **SFT Mode** | ✅ Yes (`inference_sft`) | ❌ No |
| **Predefined Speakers** | ✅ Yes (`英文女`, etc.) | ❌ No |
| **Zero-shot** | ❌ No | ✅ Yes |
| **Cross-lingual** | ❌ No | ✅ Yes |
| **Instruct2** | ❌ No | ✅ Yes |
| **Reference Audio** | Optional | **Required** |
| **Model File** | `spk2info.pt` | Not used |

## References

- [CosyVoice GitHub](https://github.com/FunAudioLLM/CosyVoice)
- [CosyVoice2 Paper](https://arxiv.org/abs/2412.10117)
- [Model on ModelScope](https://modelscope.cn/models/iic/CosyVoice2-0.5B)

## Need Help?

If you encounter issues:

1. Check the logs: `docker logs june-tts`
2. Verify reference audio exists: `ls -la /opt/CosyVoice/asset/`
3. Test health endpoint: `curl http://localhost:8000/health`
4. Check model loaded correctly in startup logs
