# Phase 1 Migration Guide: Clean Architecture Refactor

## Overview

Phase 1 introduces a clean architecture with proper separation of concerns while maintaining **100% backward compatibility** with existing code.

## What Changed

### ✅ New Architecture Components

1. **Clean Domain Models** (`app/models/domain.py`)
   - `Session` - Clean session model with proper methods
   - `Message` - Individual conversation messages
   - `SkillSession` - Skill state management
   - `SessionStats` - Statistics model

2. **Dependency Injection** (`app/core/dependencies.py`)
   - Singleton pattern for services
   - Clean dependency management
   - Easy testing and mocking

3. **SessionService** (`app/services/session/service.py`)
   - Pure business logic
   - No external dependencies mixed in
   - Clean interface and error handling

4. **External Client Abstractions** (`app/services/external/`)
   - `LiveKitClient` - Clean LiveKit integration
   - Proper error handling and logging

### ✅ Backward Compatibility

- **Original `session_manager` still works** - `session_manager_v2.py` provides a wrapper
- **All existing routes work unchanged** - They use the wrapper
- **Same API responses** - No breaking changes
- **Same functionality** - Just cleaner architecture

## Testing the Migration

### 1. Quick Test (Manual)

```bash
# Test the new architecture
cd June/services/june-orchestrator

# Run with the new main file
python -m app.main_v2

# Should see:
# ✅ June Orchestrator v7.2-PHASE1 - Clean Architecture Refactor
# ✅ PHASE 1 REFACTOR COMPLETE:
#   ✅ Clean Domain Models
#   ✅ Dependency Injection  
#   ✅ SessionService Extracted
#   ✅ External Client Abstractions
```

### 2. Verify Backward Compatibility

```bash
# Test that old imports still work
python -c "from app.session_manager_v2 import session_manager; print('✅ Old import works')"

# Test session creation
python -c "
from app.session_manager_v2 import session_manager
session = session_manager.get_or_create_session_for_room('test-room', 'test-user')
print(f'✅ Session created: {session.session_id}')
print(f'✅ Room mapping: {session.room_name}')
"
```

### 3. Integration Test

```bash
# Test the API endpoints
curl http://localhost:8080/ | jq '.version'  # Should show "7.2.0-PHASE1"
curl http://localhost:8080/healthz | jq '.features.phase1_clean_architecture'  # Should be true
```

## Migration Steps

### Option A: Gradual Migration (Recommended)

1. **Keep existing `main.py` as backup**
2. **Update import in your Docker/deployment**:
   ```dockerfile
   # Change this line:
   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
   # To this:
   CMD ["uvicorn", "app.main_v2:app", "--host", "0.0.0.0", "--port", "8080"]
   ```
3. **Test thoroughly**
4. **If satisfied, rename files**:
   ```bash
   mv app/main.py app/main_old.py
   mv app/main_v2.py app/main.py
   ```

### Option B: Direct Migration

1. **Replace main.py directly**:
   ```bash
   cp app/main_v2.py app/main.py
   ```
2. **Test immediately**

## What to Test

### Core Functionality
- [ ] **Session Creation**: New sessions via webhook
- [ ] **Session Retrieval**: Getting existing sessions
- [ ] **Message History**: Adding and retrieving messages
- [ ] **LiveKit Tokens**: Token generation works
- [ ] **Background Tasks**: Session cleanup runs
- [ ] **Health Checks**: `/healthz` endpoint works

### Voice AI Pipeline
- [ ] **STT Webhooks**: `/api/webhooks/stt` endpoint
- [ ] **Conversation Flow**: AI responses work
- [ ] **TTS Integration**: Voice responses play
- [ ] **Skill System**: Mockingbird and other skills
- [ ] **Natural Flow**: Streaming and partial transcripts

### Security Features
- [ ] **Rate Limiting**: User limits enforced
- [ ] **Cost Tracking**: AI cost monitoring
- [ ] **Circuit Breaker**: Protection works
- [ ] **Duplicate Detection**: Message deduplication

## Rollback Plan

If issues occur:

1. **Change back to original main.py**:
   ```bash
   # In your deployment/Docker
   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
   ```

2. **Or revert the file**:
   ```bash
   mv app/main.py app/main_v2.py
   mv app/main_old.py app/main.py
   ```

3. **Restart the service**

## Benefits You Get Immediately

1. **Better Logging**: Cleaner service initialization logs
2. **Easier Debugging**: Clear separation of concerns
3. **Memory Efficiency**: Better resource management
4. **Preparation for Phase 2**: Route handlers refactor will be easier

## Phase 2 Preview

Once Phase 1 is stable, Phase 2 will:
- Break down the 49KB `webhooks.py` into focused files
- Create clean request/response handling
- Extract business logic from routes
- Add comprehensive testing

## Support

If you encounter issues:
1. Check the logs for Phase 1 indicators
2. Verify backward compatibility with the test commands above
3. Use the rollback plan if needed
4. The architecture is designed to be **safe and non-breaking**

---

**Remember**: Phase 1 is designed to be **100% backward compatible**. Your existing voice AI pipeline should work exactly the same, just with cleaner architecture underneath.