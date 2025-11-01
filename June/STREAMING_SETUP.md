# June Streaming Voice AI Setup Guide

## ✨ Phase 1 & 2 Streaming Implementation Complete

Your June voice assistant now supports **streaming and concurrent processing** for significantly reduced latency!

## 🚀 What's New

### **Phase 1: Streaming Foundations**
- **STT**: Partial transcript streaming every 200ms
- **TTS**: Chunked audio generation for sub-second first-audio
- **Orchestrator**: Partial transcript handling and routing

### **Phase 2: Concurrent Processing** 
- **AI Streaming**: Token-level streaming with first-token tracking
- **Concurrent TTS**: TTS starts as soon as AI completes sentences
- **Sentence Segmentation**: Smart sentence boundary detection
- **Performance Metrics**: First-token, first-audio, end-to-end timing

## ⚙️ Configuration

### **Environment Variables (Add to your deployment)**
```bash
# STT Service
STT_STREAMING_ENABLED=true
STT_PARTIALS_ENABLED=true

# Orchestrator Service
ORCH_STREAMING_ENABLED=true
CONCURRENT_TTS_ENABLED=true
PARTIAL_SUPPORT_ENABLED=true

# TTS Service
TTS_STREAMING_ENABLED=true
```

### **Runtime Configuration**
You can toggle streaming on/off without redeployment:

```bash
# Enable streaming
curl -X POST "https://api.ozzu.world/api/streaming/configure" \
  -H "Content-Type: application/json" \
  -d '{
    "streaming_enabled": true,
    "concurrent_tts": true,
    "partial_support": true
  }'

# Check streaming status
curl "https://api.ozzu.world/api/streaming/status"
```

## 📊 Expected Performance Improvements

### **Before (Sequential Processing)**
- **Total Latency**: ~4,900ms
- **TTS Component**: ~2,300ms  
- **AI Component**: ~2,600ms

### **After Phase 1 (Streaming)**
- **First Audio**: ~500-800ms (4-6x improvement)
- **TTS First Chunk**: ~200-400ms (5-10x improvement)
- **Perceived Latency**: ~1-2s (2-3x improvement)

### **After Phase 2 (Concurrent)**
- **First Audio**: ~300-500ms (6-10x improvement)
- **AI First Token**: ~150-300ms (8-15x improvement)
- **End-to-End**: ~800-1,200ms (4-6x improvement)

## 🧪 Testing the Streaming Features

### **1. Test Streaming Status**
```bash
# Check if all services support streaming
curl "https://june-stt.ozzu.world/" | jq .streaming
curl "https://june-tts.ozzu.world/streaming/status"
curl "https://api.ozzu.world/api/streaming/status"
```

### **2. Test Streaming TTS Directly**
```bash
# Test streaming TTS endpoint
curl -X POST "https://june-tts.ozzu.world/stream-to-room" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "This is a streaming TTS test. You should hear this much faster!",
    "language": "en",
    "exaggeration": 0.6,
    "cfg_weight": 0.8
  }'
```

### **3. Monitor Streaming Metrics**
```bash
# Check streaming performance metrics
curl "https://api.ozzu.world/api/streaming/status" | jq .metrics

# Watch metrics in real-time
watch -n 2 'curl -s "https://api.ozzu.world/api/streaming/status" | jq ".metrics"'
```

### **4. Compare Streaming vs Regular**
```bash
# Force regular (non-streaming) processing
curl -X POST "https://api.ozzu.world/api/streaming/configure" \
  -d '{"streaming_enabled": false}'
  
# Test conversation and note timing
# Then enable streaming and test again
curl -X POST "https://api.ozzu.world/api/streaming/configure" \
  -d '{"streaming_enabled": true}'
```

## 📝 Key Metrics to Watch

### **Streaming Metrics (New)**
- `avg_first_token_ms`: How fast AI starts responding
- `avg_first_audio_ms`: How fast TTS starts playing
- `concurrent_tts_triggers`: How many TTS calls started before AI finished
- `partial_transcripts_received`: STT streaming effectiveness

### **Expected Values**
- **First Token**: <500ms (down from 2,600ms)
- **First Audio**: <300ms (down from 2,300ms)
- **Concurrent TTS**: >80% of conversations
- **End-to-End**: <1,500ms (down from 4,900ms)

## 🔍 Troubleshooting

### **If Streaming Doesn't Improve Performance**
1. Check feature flags are enabled in all services
2. Verify Gemini API supports streaming (fallback if not)
3. Monitor metrics for concurrent TTS triggers
4. Check logs for "First token" and "First audio" timing

### **If Services Crash**
1. Disable streaming: Set all `*_STREAMING_ENABLED=false`
2. Services will fall back to regular processing
3. Check logs for specific errors

### **Streaming Disabled Fallback**
All services gracefully fall back to your current working implementation if streaming is disabled.

## 💮 Performance Tuning

### **For Even Better Performance**
1. **Reduce AI max tokens**: Set `max_output_tokens=150` for faster completion
2. **Tune TTS chunk size**: Smaller chunks = faster first audio, more overhead
3. **Optimize sentence detection**: Adjust `min_sentence_chars` in streaming service
4. **Enable GPU optimizations**: Ensure torch.compile is working (already done)

### **Next Phase Candidates**
1. **ElevenLabs Flash v2.5**: Replace Chatterbox for ~75ms TTS 
2. **Groq + Llama**: Replace Gemini for ~200ms AI responses
3. **Local STT**: Add Whisper-small locally for ~100ms transcription
4. **Speech-to-Speech**: Single model replacing STT+AI+TTS

## 🏁 Success Indicators

After deploying these changes, you should see:
1. **Logs showing "First token in Xms"** - AI streaming working
2. **Logs showing "First audio chunk in Xms"** - TTS streaming working  
3. **Concurrent TTS trigger logs** - Pipeline parallelization working
4. **Partial transcript logs** - STT streaming working
5. **Overall latency <2 seconds** - Major improvement from 4.9s

Enjoy your much faster voice assistant! 🎉