# Changelog - June Platform

All notable changes to the June platform will be documented in this file.

## [2025-10-12] - Janus CrashLoopBackOff Fix 🎉

### Fixed
- **Janus Gateway CrashLoopBackOff**: Resolved startup failures with modern Janus image
- **STUN Authentication Issues**: Fixed compatibility between Janus and STUNner
- **WebRTC Connectivity**: Improved ICE candidate generation and client connectivity

### Changed
- **Janus Docker Image**: Updated from `swmansion/janus-gateway` (v0.11.8, 2022) to `sucwangsr/janus-webrtc-gateway-docker:latest` (v1.3.2, 2025)
- **STUNner Configuration**: 
  - Realm: `june.ozzu.world` → `turn.ozzu.world`
  - AuthType: `static` → `plaintext` for better STUN compatibility

### Technical Details
- **Root Cause**: Old Janus image couldn't handle STUNner's authentication requirements during STUN BINDING tests
- **Impact**: Modern image eliminates authentication mismatches and provides better WebRTC support
- **Testing**: All services now start successfully - IDP, Orchestrator, Janus Gateway, PostgreSQL, STUNner

### Files Modified
- `helm/june-platform/values.yaml` - Updated Janus image configuration
- `k8s/stunner-manifests.yaml` - Improved STUNner compatibility settings

---

## Previous Versions

### [2025-10-XX] - Initial Platform Setup
- Created June microservices platform with Helm charts
- Integrated Keycloak for identity management
- Added STUNner for WebRTC TURN functionality
- Implemented CI/CD with GitHub Actions