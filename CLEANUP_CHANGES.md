# TTS Cleanup Changes

## What Changed

### ✅ Removed
- `June/services/june-tts/` - Old TTS microservice
- TTS-related Kubernetes manifests
- TTS references in CI/CD pipeline
- Unused deployment scripts

### ✅ Added
- `external_tts_client.py` - Client for external OpenVoice service
- `core-services-no-tts.yaml` - Updated Kubernetes manifest
- IDP authentication for external TTS calls

### ✅ Updated
- Orchestrator configured for external TTS
- Ingress removes TTS endpoints
- Build pipeline excludes TTS service

## Next Steps Required

1. **Update orchestrator app.py** with external TTS client:
   ```python
   # Add to imports
   from external_tts_client import ExternalTTSClient
   
   # Replace TTS client initialization (see app_tts_patch.py for details)
   ```

2. **Set external TTS URL**:
   ```bash
   # Encode your OpenVoice service URL
   echo -n "https://your-openvoice-service.com" | base64
   
   # Update the secret
   kubectl patch secret june-secrets -n june-services \
     --patch='{"data":{"EXTERNAL_TTS_URL":"<base64-encoded-url>"}}'
   ```

3. **Deploy updated services**:
   ```bash
   kubectl apply -f k8s/june-services/core-services-no-tts.yaml
   ```

4. **Test integration**:
   ```bash
   kubectl port-forward -n june-services service/june-orchestrator 8080:8080
   curl http://localhost:8080/healthz
   ```

## Architecture Now

```
┌─────────────────┐    ┌─────────────────┐
│   Orchestrator  │───▶│      STT        │
│                 │    │   (Internal)    │
│                 │    │                 │
│                 │    └─────────────────┘
│                 │    ┌─────────────────┐
│                 │───▶│   Keycloak IDP  │
│                 │    │   (Internal)    │
│                 │    └─────────────────┘
│                 │           │
│                 │           │ IDP Auth
│                 │           ▼
│                 │────────────────────────▶ ┌─────────────────┐
└─────────────────┘      HTTPS + Auth       │   OpenVoice     │
                                            │   TTS Service   │
                                            │   (External)    │
                                            └─────────────────┘
```
