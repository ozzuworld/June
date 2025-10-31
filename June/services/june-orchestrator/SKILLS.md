# June Skills System - Voice Cloning & AI Capabilities

**June Orchestrator v6.0.0** - Skill-based AI assistant with voice cloning demonstrations

## 🤖 Architecture Overview

### **Two-Mode Operation:**

**1. Normal Conversation Mode (Default):**
```
User: "Hey June, how's the weather?"
June: *Responds in consistent Claribel Dervla voice* 🎤
```

**2. Skill Mode (On-Demand):**
```
User: "June, use your skill mockingbird"
June: "Mockingbird skill activated!" *Claribel voice*
User: "Hello, this is my voice"
June: "Hello, this is my voice" *User's cloned voice* 🎭
```

### **Design Philosophy:**
- **Consistent daily experience** with June's familiar voice
- **Impressive skill demonstrations** for showcasing capabilities
- **Expandable architecture** for future AI skills
- **Clear mode separation** to avoid confusion

## 🎭 Available Skills

### **🐦 Mockingbird (Voice Cloning) - ✅ Ready**

**Purpose:** Demonstrate voice cloning capabilities

**Activation Triggers:**
- "June, use your skill mockingbird"
- "activate mockingbird"
- "show me voice cloning"
- "demonstrate voice cloning"
- "mimic my voice"
- "copy my voice"

**Flow:**
```
1. User: "June, use your skill mockingbird"
2. June: "🎭 Mockingbird skill activated! Say something, and I'll speak back in your voice."
3. User: *Says anything*
4. June: *Repeats in user's cloned voice*
5. User: "exit" (or auto-exit after 3 turns)
6. June: "Mockingbird demonstration complete!"
```

**Technical Implementation:**
- Captures user's voice from LiveKit audio stream
- Creates temporary voice profile with reference audio
- Uses june-tts v3.0.0 multi-reference `speaker_wav` API
- Auto-cleans voice profiles after demonstration

### **🌍 Translator - 🚧 Coming Soon**

**Purpose:** Multi-language translation with voice synthesis

**Planned Triggers:**
- "June, translate this to Spanish"
- "use your skill translator"

### **📚 Storyteller - 🚧 Coming Soon**

**Purpose:** Interactive storytelling with character voices

**Planned Triggers:**
- "June, tell me a story"
- "use your skill storyteller"

## 🛠️ Technical Implementation

### **Skill Detection System:**

```python
# From skill_service.py
skill_trigger = skill_service.detect_skill_trigger(user_text)
if skill_trigger:
    skill_name, skill_def = skill_trigger
    # Activate skill...
```

### **Voice Cloning Integration:**

```python
# Normal conversation (June's voice)
payload = {
    "text": ai_response,
    "language": "en",
    "speaker": "Claribel Dervla"  # Consistent June voice
}

# Skill demonstration (user's cloned voice)
payload = {
    "text": ai_response,
    "language": "en",
    "speaker_wav": ["/app/voice_profiles/user123/reference.wav"]  # Multi-reference
}
```

### **Session State Management:**

```python
class SkillSession:
    active_skill: Optional[str] = None
    context: Dict[str, Any] = {}
    turn_count: int = 0
    waiting_for_input: bool = False
```

## 📡 API Endpoints

### **Core Skill Endpoints:**

#### `GET /api/skills`
List available skills
```json
{
  "skills": {
    "mockingbird": {
      "name": "mockingbird",
      "type": "voice_cloning",
      "description": "Voice cloning demonstration",
      "ready": true,
      "triggers": ["use your skill mockingbird"]
    }
  }
}
```

#### `GET /api/skills/help`
Get help text for all skills
```json
{
  "help_text": "Here are my available skills:\n\n🔹 **Mockingbird** (✅ Ready)\n   Voice cloning demonstration - June mimics user voices\n   Say 'June, use your skill mockingbird' to activate"
}
```

#### `POST /api/sessions/{id}/skills/{skill}/deactivate`
Manually deactivate a skill
```json
{
  "status": "success",
  "deactivated_skill": "mockingbird",
  "message": "Skill mockingbird deactivated"
}
```

### **Enhanced Session Endpoints:**

#### `GET /api/sessions/stats`
Session statistics with skill usage
```json
{
  "session_stats": {
    "active_sessions": 3,
    "active_skills": 1,
    "skills_in_use": {"mockingbird": 1}
  },
  "voice_profile_stats": {
    "total_profiles": 2,
    "total_references": 5
  }
}
```

#### `GET /api/sessions/{id}/history`
Session history with skill context
```json
{
  "history": [...],
  "skill_state": {
    "active_skill": "mockingbird",
    "turn_count": 2,
    "waiting_for_input": true
  }
}
```

## 💬 Conversation Examples

### **Normal Daily Conversation:**

```
User: "Hey June, what's the weather like?"
June: "The weather today is partly cloudy with a high of 72°F." 
      *[Claribel Dervla voice - consistent June personality]*

User: "Thanks! Can you set a reminder for 3 PM?"
June: "I'd be happy to help, but I don't have reminder capabilities yet."
      *[Same consistent voice]*
```

### **Mockingbird Skill Demonstration:**

```
User: "June, show me voice cloning"
June: "🎭 Mockingbird skill activated! Say something, and I'll speak back in your voice."
      *[June's normal voice]*

User: "This is pretty amazing technology!"
June: "Perfect! I heard you say: 'This is pretty amazing technology!' 
       Now let me demonstrate by speaking in your voice..."
      *[June's normal voice]*

June: "This is pretty amazing technology!"
      *[User's cloned voice - demonstration!]*

User: "Wow, that's incredible!"
June: "Sure! Here's another demonstration in your voice: Wow, that's incredible!"
      *[User's cloned voice]*

User: "exit"
June: "Mockingbird demonstration complete! I'm returning to my normal voice now."
      *[Back to Claribel Dervla voice]*
```

## 🔧 Configuration

### **Environment Variables:**

```bash
# Enhanced orchestrator config
AI_MODEL=gemini-2.0-flash-exp
AI_VOICE_MODE=true
AI_MAX_OUTPUT_TOKENS=200

# TTS service (must match june-tts v3.0.0)
TTS_SERVICE_URL=http://june-tts:8000

# Voice profile storage
VOICE_PROFILE_STORAGE=/app/voice_profiles

# Session management
MAX_HISTORY_MESSAGES=20
SESSION_TIMEOUT_HOURS=24
CLEANUP_INTERVAL_MINUTES=60
```

### **Storage Structure:**

```
/app/voice_profiles/
├── profiles.json           # Profile metadata
├── user123/
│   ├── mockingbird_20251031_120000.wav
│   └── mockingbird_20251031_120030.wav
└── user456/
    └── mockingbird_20251031_130000.wav
```

## 🚀 Usage Patterns

### **For Daily AI Assistant:**
- Users interact normally without mentioning skills
- June responds consistently in Claribel Dervla voice
- Full conversation memory and context maintained
- Fast response times and reliable experience

### **For Voice Cloning Demonstrations:**
- Users explicitly activate mockingbird skill
- June captures user's voice from next utterance
- June demonstrates by speaking in user's voice
- Automatic cleanup after demonstration
- Clear skill entry/exit states

### **For Skill Development:**
- Skills are modular and expandable
- Each skill has defined triggers and behavior
- Session state tracks skill context
- Easy to add new skills without affecting core functionality

## 🐛 Troubleshooting

### **Common Issues:**

**"Skill not activating"**
- Check trigger phrases in logs
- Verify skill_service initialization
- Check case sensitivity in detection

**"Voice cloning not working"**
- Verify june-tts v3.0.0 is running
- Check voice_profile_service storage permissions
- Ensure reference audio quality (6+ seconds recommended)

**"TTS API mismatch errors"**
- Ensure orchestrator uses `speaker_wav` (not `voice_id`)
- Verify june-tts v3.0.0 endpoints are available
- Check TTS service logs for API compatibility

### **Debug Commands:**

```bash
# Check skill system
curl http://api.ozzu.world/api/skills

# Check session with skill state
curl http://api.ozzu.world/api/sessions/{session_id}/history

# Get voice profile stats
curl http://api.ozzu.world/api/sessions/stats

# Check orchestrator health
curl http://api.ozzu.world/healthz
```

### **Log Messages to Monitor:**

```
✅ Normal conversation:
💬 Normal conversation processing...
🔊 Triggering normal TTS for room: ozzu-main

✅ Skill activation:
🎯 Detected skill trigger: 'use your skill mockingbird' -> mockingbird
🤖 Activating skill: mockingbird for user ozzu-app

✅ Voice cloning:
🎭 Triggering voice cloning TTS for room: ozzu-main (user: ozzu-app)
📁 Using 2 reference files for voice cloning
✅ TTS triggered successfully: 1247.3ms, 89344 bytes
```

## 🚀 Deployment

Your enhanced orchestrator is backward compatible:

1. **Existing functionality preserved** - normal conversations work exactly as before
2. **New skill system** adds capabilities without breaking changes
3. **Voice profile storage** is optional and auto-created
4. **june-tts v3.0.0 compatible** - uses proper `speaker_wav` API

### **Rebuild and Deploy:**

```bash
# Orchestrator (if running in Kubernetes)
cd June/services/june-orchestrator
docker build -t june-orchestrator:6.0.0 .
kubectl rollout restart deployment/june-orchestrator

# june-vast (if using combined image)
cd June/services/june-vast  
docker build -t june-vast:latest .
# Restart your vast.ai deployment
```

## 📈 Future Skills Roadmap

### **Phase 1 (Current):** ✅
- Mockingbird voice cloning skill
- Basic skill detection and management
- Session state integration

### **Phase 2:** 🚧
- Translator skill with voice synthesis in target language
- Storyteller skill with multiple character voices
- Voice profile persistence and management

### **Phase 3:** 📅
- Custom skill creation API
- Voice style transfer (emotion, accent)
- Multi-participant voice cloning
- Advanced skill chaining

---

**June v6.0.0** - Your AI assistant just got a whole lot more impressive! 🎆