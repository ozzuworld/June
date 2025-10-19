# 🧹 Repository Cleanup & LiveKit Integration Fix

## What Was Fixed

### **Root Cause**
The services had **conflicting/confusing code** with multiple approaches for LiveKit integration. Services were **not actually connecting** to the "ozzu-main" LiveKit room as participants.

### **Issues Resolved**

1. **STT Service**: Had duplicate main files (`app.py` vs `livekit_participant.py`) causing confusion
2. **TTS Service**: LiveKit connection code existed but wasn't properly integrated 
3. **Orchestrator**: Using external LiveKit URL instead of internal Kubernetes service
4. **Configuration**: Mixed external/internal URLs causing connection failures

## 📁 Files Changed

### **STT Service (`June/services/june-stt/`)**
- ✅ **NEW**: `main.py` - Clean service with proper LiveKit room connection
- ✅ **UPDATED**: `config.py` - Correct internal Kubernetes URLs
- ✅ **UPDATED**: `requirements.txt` - Added LiveKit dependencies
- ✅ **UPDATED**: `Dockerfile` - Uses `main.py` as entrypoint
- ❌ **DELETED**: `app.py` - Old confusing file
- ❌ **DELETED**: `livekit_participant.py` - Duplicate logic file

### **TTS Service (`June/services/june-tts/`)**
- ✅ **UPDATED**: `main.py` - Clean service with proper LiveKit room connection
- ✅ **UPDATED**: `config.py` - Correct internal Kubernetes URLs
- ✅ **UPDATED**: `requirements.txt` - Added LiveKit dependencies
- ❌ **DELETED**: `livekit_participant.py` - Duplicate logic file

### **Orchestrator Service (`June/services/june-orchestrator/`)**
- ✅ **UPDATED**: `app/config.py` - Fixed to use internal LiveKit URLs

## 🔧 How It Works Now

### **Startup Sequence**
1. **LiveKit Server** starts first
2. **STT Service** starts → **automatically joins "ozzu-main" room** as "june-stt" participant
3. **TTS Service** starts → **automatically joins "ozzu-main" room** as "june-tts" participant  
4. **Orchestrator** starts → connects to internal services (doesn't join room)

### **Runtime Behavior**
1. **Frontend joins "ozzu-main"** → STT and TTS are already waiting
2. **User speaks** → STT hears audio automatically, transcribes
3. **STT sends transcript** → Orchestrator processes with LLM
4. **Orchestrator calls TTS** → TTS publishes AI response to room
5. **Frontend hears response** → Complete conversation loop

## 🚀 Deployment Commands

### **Redeploy Updated Services**
```bash
# Navigate to project root
cd /home/user/June

# Rebuild and redeploy STT service
kubectl delete deployment june-stt -n june-services
kubectl apply -f helm/june-platform/templates/june-stt.yaml

# Rebuild and redeploy TTS service  
kubectl delete deployment june-tts -n june-services
kubectl apply -f helm/june-platform/templates/june-tts.yaml

# Restart orchestrator to pick up config changes
kubectl rollout restart deployment june-orchestrator -n june-services
```

### **Expected Logs After Fix**

**STT Service Logs:**
```
🚀 Starting June STT Service with LiveKit Integration
✅ Whisper model initialized
🔌 STT connecting to LiveKit room: ozzu-main
✅ STT connected to ozzu-main room
🎤 Listening for audio tracks to transcribe...
```

**TTS Service Logs:**
```
🚀 Starting June TTS Service on device: cuda
✅ TTS model initialized  
🔊 TTS connecting to LiveKit room: ozzu-main
✅ TTS connected to ozzu-main room
🎤 TTS audio track published and ready
```

**Orchestrator Service Logs:**
```
🚀 June Orchestrator v3.0 - LiveKit Integration
🔧 LiveKit: ws://livekit-livekit-server:80
🔧 TTS: http://june-tts:8000
🔧 STT: http://june-stt:8080
```

## 🔍 Verification Commands

### **Check Service Status**
```bash
# Check all pods are running
kubectl get pods -n june-services

# Check service logs for LiveKit connections
kubectl logs -l app=june-stt -n june-services | grep -i livekit
kubectl logs -l app=june-tts -n june-services | grep -i livekit
kubectl logs -l app=june-orchestrator -n june-services | grep -i livekit
```

### **Test Service Endpoints**
```bash
# Test STT health
kubectl exec -it deployment/june-orchestrator -n june-services -- \
  curl http://june-stt:8080/healthz

# Test TTS health  
kubectl exec -it deployment/june-orchestrator -n june-services -- \
  curl http://june-tts:8000/healthz

# Check LiveKit server
kubectl exec -it deployment/june-orchestrator -n june-services -- \
  curl http://livekit-livekit-server:80
```

## 🎯 What Should Happen

### **Before Fix**
- ❌ Services start but don't connect to LiveKit room
- ❌ No LiveKit connection logs visible
- ❌ Frontend joins empty room, no AI interaction

### **After Fix**
- ✅ Services automatically join "ozzu-main" room at startup
- ✅ Clear LiveKit connection logs visible
- ✅ Frontend joins room with STT/TTS already present
- ✅ Immediate voice AI conversation capability

## 🔒 Security Notes

- All services use **internal Kubernetes DNS** (no external URLs)
- LiveKit credentials use defaults for development
- Services communicate within cluster only
- External access only through ingress/stunner

---

**Repository is now clean and properly configured for LiveKit room-based voice AI interactions!** 🎉