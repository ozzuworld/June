# June Orchestrator Improvement Plan
## Connecting Enhanced Components for Natural AI Assistant Experience

**Document Version:** 1.0
**Date:** 2025-11-21
**Status:** Awaiting Approval

---

## EXECUTIVE SUMMARY

This plan connects your existing sophisticated dialogue management components (IntentClassifier, SlotExtractor, DialogueState, ConversationManager) into the actual conversation flow. Currently these components exist but are bypassed - the webhook goes directly to SimpleVoiceAssistant which relies solely on Gemini LLM function calling.

**Goal:** Transform from "simple chatbot" → "natural AI assistant" with reliable skill activation and state-aware conversations.

**Approach:** Incremental refactoring in 3 phases, each independently testable.

---

## CURRENT VS PROPOSED ARCHITECTURE

### Current Flow (v10.0.0-SIMPLE)
```
┌─────────────────────────────────────────────────────────┐
│ STT Webhook                                             │
│   ↓                                                     │
│ SimpleVoiceAssistant.handle_transcript()                │
│   ↓                                                     │
│ Gemini LLM (with function calling tools)                │
│   ├─ Tool called? Execute it                           │
│   └─ No tool? Generate response                        │
│   ↓                                                     │
│ TTS                                                     │
└─────────────────────────────────────────────────────────┘
```

**Problems:**
- Skill activation unreliable (depends on LLM interpretation)
- No conversation state management
- No confirmation flows
- Every interaction feels isolated

### Proposed Flow (Enhanced)
```
┌─────────────────────────────────────────────────────────┐
│ STT Webhook                                             │
│   ↓                                                     │
│ ConversationManager.process_user_input()                │
│   ├─ Intent Classification (rule-based)                │
│   ├─ Slot Extraction                                   │
│   ├─ Dialogue State Update                             │
│   └─ Context Update                                    │
│   ↓                                                     │
│ SkillOrchestrator.route_intent()                        │
│   ├─ Skill intent? → Execute skill                     │
│   ├─ Missing slots? → Ask for slots                    │
│   ├─ Need confirmation? → Confirm action               │
│   └─ General chat? → Call Gemini                       │
│   ↓                                                     │
│ ResponseGenerator.generate()                            │
│   ├─ Natural language response                         │
│   └─ State-aware phrasing                              │
│   ↓                                                     │
│ TTS                                                     │
└─────────────────────────────────────────────────────────┘
```

**Benefits:**
- ✅ Deterministic skill activation
- ✅ State-aware conversations
- ✅ Confirmation flows for critical actions
- ✅ Multi-turn dialogues
- ✅ Context continuity

---

## IMPLEMENTATION PHASES

### Phase 1: Connect Intent Classification (CRITICAL PATH)
**Goal:** Wire ConversationManager into the flow, use intent results
**Impact:** Skills activate reliably
**Risk:** Low (ConversationManager already tested)
**Duration:** 1-2 hours implementation, 1 hour testing

### Phase 2: Add Skill Orchestration Layer
**Goal:** Route intents to skills, add confirmation flows
**Impact:** Natural multi-turn conversations
**Risk:** Medium (new component)
**Duration:** 2-3 hours implementation, 2 hours testing

### Phase 3: State-Aware Response Generation
**Goal:** Use dialogue states to control conversation style
**Impact:** Conversations feel contextual and natural
**Risk:** Low (enhances existing)
**Duration:** 1-2 hours implementation, 1 hour testing

---

## PHASE 1: CONNECT INTENT CLASSIFICATION

### Overview
Make the webhook call `ConversationManager.process_user_input()` first, then use the intent classification result to decide whether to call a skill directly or fall back to Gemini.

### Files to Modify

#### 1.1 `app/routes/webhooks.py`

**Current code (lines 144-154):**
```python
@router.post("/stt", status_code=200)
async def handle_stt_webhook(request: Request):
    try:
        data = await request.json()
        session_id = data.get("session_id")
        room_name = data.get("room_name")
        text = data.get("text")
        language = data.get("language", "en")

        # Goes straight to assistant
        await assistant.handle_transcript(session_id, room_name, text, language)

        return {"status": "success"}
```

**New code:**
```python
@router.post("/stt", status_code=200)
async def handle_stt_webhook(request: Request):
    try:
        data = await request.json()
        session_id = data.get("session_id")
        room_name = data.get("room_name")
        text = data.get("text")
        language = data.get("language", "en")

        # Phase 1: Add intent classification
        from app.services.conversation_manager import ConversationManager
        from app.services.skill_orchestrator import SkillOrchestrator

        # Get or create conversation manager for this session
        conversation_manager = get_conversation_manager(session_id)
        skill_orchestrator = get_skill_orchestrator(session_id)

        # Process input with intent classification
        processing_result = await conversation_manager.process_user_input(
            text=text,
            language=language
        )

        # Route based on intent
        response = await skill_orchestrator.route_intent(
            session_id=session_id,
            room_name=room_name,
            processing_result=processing_result,
            assistant=assistant
        )

        return {"status": "success", "intent": processing_result.intent}

    except Exception as e:
        logger.error(f"Error in STT webhook: {e}")
        return {"status": "error", "message": str(e)}
```

**Changes:**
- ✅ Calls `conversation_manager.process_user_input()` first
- ✅ Gets intent, slots, dialogue state
- ✅ Routes to skill orchestrator
- ✅ Returns intent for debugging

#### 1.2 Create `app/services/session_managers.py` (NEW FILE)

**Purpose:** Manage session-scoped instances of ConversationManager and SkillOrchestrator

```python
"""
Session Managers - Singleton pattern for conversation components
"""
from typing import Dict
from app.services.conversation_manager import ConversationManager
from app.services.skill_orchestrator import SkillOrchestrator
from app.services.intent_classifier import IntentClassifier
from app.services.slot_extractor import SlotExtractor

# Global registries
_conversation_managers: Dict[str, ConversationManager] = {}
_skill_orchestrators: Dict[str, SkillOrchestrator] = {}

def get_conversation_manager(session_id: str) -> ConversationManager:
    """Get or create ConversationManager for session"""
    if session_id not in _conversation_managers:
        intent_classifier = IntentClassifier()
        slot_extractor = SlotExtractor()
        _conversation_managers[session_id] = ConversationManager(
            session_id=session_id,
            intent_classifier=intent_classifier,
            slot_extractor=slot_extractor
        )
    return _conversation_managers[session_id]

def get_skill_orchestrator(session_id: str) -> SkillOrchestrator:
    """Get or create SkillOrchestrator for session"""
    if session_id not in _skill_orchestrators:
        _skill_orchestrators[session_id] = SkillOrchestrator(session_id)
    return _skill_orchestrators[session_id]

def clear_session(session_id: str):
    """Clear session data (call on session end)"""
    if session_id in _conversation_managers:
        del _conversation_managers[session_id]
    if session_id in _skill_orchestrators:
        del _skill_orchestrators[session_id]
```

#### 1.3 Create `app/services/skill_orchestrator.py` (NEW FILE - Phase 1 Version)

**Purpose:** Route intents to appropriate handlers (skills or general chat)

```python
"""
Skill Orchestrator - Routes intents to skills or general chat
Phase 1: Basic routing with fallback to Gemini
"""
import logging
from typing import Any, Optional
from dataclasses import dataclass

from app.services.conversation_manager import ProcessingResult
from app.services.mockingbird_skill import MockingbirdSkill, MockingbirdState
from app.services.simple_voice_assistant import SimpleVoiceAssistant

logger = logging.getLogger(__name__)

@dataclass
class OrchestrationResult:
    """Result of intent orchestration"""
    handled: bool
    response: Optional[str] = None
    should_speak: bool = True
    skill_activated: bool = False

class SkillOrchestrator:
    """
    Routes intents to appropriate skills or general chat.

    Phase 1: Direct intent-to-skill mapping
    Future: Skill registry, confirmation flows, slot filling
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.mockingbird = MockingbirdSkill()

        # Intent to handler mapping
        self.intent_handlers = {
            "mockingbird_enable": self._handle_mockingbird_enable,
            "mockingbird_disable": self._handle_mockingbird_disable,
            "mockingbird_status": self._handle_mockingbird_status,
            "greeting": self._handle_greeting,
            "farewell": self._handle_farewell,
            "help": self._handle_help,
        }

    async def route_intent(
        self,
        session_id: str,
        room_name: str,
        processing_result: ProcessingResult,
        assistant: SimpleVoiceAssistant
    ) -> OrchestrationResult:
        """
        Route intent to appropriate handler.

        Args:
            session_id: Session identifier
            room_name: LiveKit room name
            processing_result: Result from ConversationManager.process_user_input()
            assistant: SimpleVoiceAssistant instance (for fallback)

        Returns:
            OrchestrationResult with response and metadata
        """
        intent = processing_result.intent
        confidence = processing_result.confidence

        logger.info(f"Routing intent: {intent} (confidence: {confidence:.2f})")

        # Check if we have a handler for this intent
        if intent in self.intent_handlers:
            # High confidence intent - handle directly
            if confidence >= 0.7:
                try:
                    result = await self.intent_handlers[intent](
                        processing_result=processing_result,
                        room_name=room_name
                    )

                    # Send response to TTS if handled
                    if result.handled and result.should_speak:
                        await assistant.send_to_tts(
                            session_id=session_id,
                            room_name=room_name,
                            text=result.response,
                            language=processing_result.context.user_profile.get("preferred_language", "en")
                        )

                    return result

                except Exception as e:
                    logger.error(f"Error handling intent {intent}: {e}")
                    # Fall through to general chat on error

        # No handler or low confidence - fall back to general chat
        logger.info(f"Falling back to general chat for: {processing_result.original_text}")
        await assistant.handle_transcript(
            session_id=session_id,
            room_name=room_name,
            text=processing_result.original_text,
            language=processing_result.context.user_profile.get("preferred_language", "en"),
            bypass_intent_classification=True  # We already classified
        )

        return OrchestrationResult(handled=True, should_speak=False)  # Assistant handles TTS

    # ==================== INTENT HANDLERS ====================

    async def _handle_mockingbird_enable(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle mockingbird enable intent"""
        logger.info(f"Enabling mockingbird for session {self.session_id}")

        try:
            # Check current state
            status = self.mockingbird.get_status(self.session_id)
            current_state = status.get("state")

            if current_state == MockingbirdState.ACTIVE:
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird is already active. I'm already using your cloned voice!",
                    skill_activated=False
                )

            if current_state in [MockingbirdState.CAPTURING, MockingbirdState.CLONING]:
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird is already in progress. Please wait...",
                    skill_activated=False
                )

            # Enable mockingbird
            result = await self.mockingbird.enable(self.session_id, room_name)

            if result.get("success"):
                return OrchestrationResult(
                    handled=True,
                    response="Activating mockingbird! Please speak for about 8 seconds so I can clone your voice. Just talk naturally - tell me about your day or read something.",
                    skill_activated=True
                )
            else:
                error = result.get("error", "Unknown error")
                return OrchestrationResult(
                    handled=True,
                    response=f"Sorry, I couldn't activate mockingbird: {error}",
                    skill_activated=False
                )

        except Exception as e:
            logger.error(f"Error enabling mockingbird: {e}")
            return OrchestrationResult(
                handled=True,
                response="Sorry, I encountered an error activating mockingbird. Please try again.",
                skill_activated=False
            )

    async def _handle_mockingbird_disable(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle mockingbird disable intent"""
        logger.info(f"Disabling mockingbird for session {self.session_id}")

        try:
            result = await self.mockingbird.disable(self.session_id)

            if result.get("success"):
                return OrchestrationResult(
                    handled=True,
                    response="I've switched back to my default voice. How does this sound?",
                    skill_activated=False
                )
            else:
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird wasn't active, so I'm already using my default voice.",
                    skill_activated=False
                )

        except Exception as e:
            logger.error(f"Error disabling mockingbird: {e}")
            return OrchestrationResult(
                handled=True,
                response="Sorry, I had trouble changing voices.",
                skill_activated=False
            )

    async def _handle_mockingbird_status(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle mockingbird status check intent"""
        try:
            status = self.mockingbird.get_status(self.session_id)
            state = status.get("state")

            responses = {
                MockingbirdState.INACTIVE: "Mockingbird is not active. I'm using my default voice. Would you like me to clone your voice?",
                MockingbirdState.AWAITING_SAMPLE: "Mockingbird is waiting for you to speak so I can clone your voice.",
                MockingbirdState.CAPTURING: "I'm currently recording your voice sample...",
                MockingbirdState.CLONING: "I'm processing your voice clone. This will just take a moment...",
                MockingbirdState.ACTIVE: "Mockingbird is active! I'm using your cloned voice right now.",
                MockingbirdState.ERROR: "Mockingbird encountered an error. Would you like to try again?"
            }

            response = responses.get(state, "I'm not sure what mockingbird's status is.")

            return OrchestrationResult(
                handled=True,
                response=response,
                skill_activated=False
            )

        except Exception as e:
            logger.error(f"Error checking mockingbird status: {e}")
            return OrchestrationResult(
                handled=True,
                response="I'm having trouble checking the mockingbird status.",
                skill_activated=False
            )

    async def _handle_greeting(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle greeting intent"""
        # Could personalize based on time of day, user history, etc.
        user_name = processing_result.context.user_profile.get("name", "")
        greeting = f"Hello{' ' + user_name if user_name else ''}! How can I help you today?"

        return OrchestrationResult(
            handled=True,
            response=greeting,
            skill_activated=False
        )

    async def _handle_farewell(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle farewell intent"""
        return OrchestrationResult(
            handled=True,
            response="Goodbye! Feel free to come back anytime.",
            skill_activated=False
        )

    async def _handle_help(
        self,
        processing_result: ProcessingResult,
        room_name: str
    ) -> OrchestrationResult:
        """Handle help intent"""
        help_text = (
            "I'm June, your AI assistant! I can have conversations with you, "
            "answer questions, and use special skills. "
            "For example, you can ask me to enable 'mockingbird' to clone your voice, "
            "or just chat with me about anything you'd like to know."
        )

        return OrchestrationResult(
            handled=True,
            response=help_text,
            skill_activated=False
        )
```

#### 1.4 Modify `app/services/simple_voice_assistant.py`

**Changes needed:**
1. Add `bypass_intent_classification` parameter to `handle_transcript()`
2. Remove tool calling from system prompt when called from orchestrator
3. Keep tool calling for fallback mode (general chat)

**Current signature (line ~400):**
```python
async def handle_transcript(
    self,
    session_id: str,
    room_name: str,
    text: str,
    language: str = "en"
):
```

**New signature:**
```python
async def handle_transcript(
    self,
    session_id: str,
    room_name: str,
    text: str,
    language: str = "en",
    bypass_intent_classification: bool = False  # NEW
):
```

**Modify tool inclusion logic (around line 500-560):**
```python
# Build tools list
tools = []
if not bypass_intent_classification:
    # Include tools only in fallback mode
    # (When called directly without intent classification)
    tools = self._get_gemini_tools()

# Build system prompt
system_prompt = self._build_system_prompt(
    include_tools=(len(tools) > 0)
)
```

**Extract send_to_tts as public method** (currently around line 800):
```python
async def send_to_tts(
    self,
    session_id: str,
    room_name: str,
    text: str,
    language: str = "en"
):
    """
    Public method to send text to TTS service.
    Can be called by SkillOrchestrator.
    """
    # Existing TTS logic here
    await self._stream_to_tts(session_id, room_name, text, language)
```

### Phase 1 Testing Plan

#### 1. Unit Tests
Create `tests/test_skill_orchestrator.py`:
```python
import pytest
from app.services.skill_orchestrator import SkillOrchestrator, OrchestrationResult
from app.services.conversation_manager import ProcessingResult, ConversationContext

@pytest.mark.asyncio
async def test_mockingbird_enable_intent():
    orchestrator = SkillOrchestrator("test_session")

    # Mock processing result with mockingbird_enable intent
    processing_result = ProcessingResult(
        intent="mockingbird_enable",
        confidence=0.95,
        slots={},
        original_text="enable mockingbird",
        context=ConversationContext(session_id="test_session")
    )

    # Should route to mockingbird handler
    result = await orchestrator._handle_mockingbird_enable(
        processing_result=processing_result,
        room_name="test_room"
    )

    assert result.handled == True
    assert "mockingbird" in result.response.lower()
```

#### 2. Integration Tests
Test full flow:
```bash
# Test 1: Mockingbird activation
curl -X POST http://localhost:8000/api/webhooks/stt \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test123",
    "room_name": "room123",
    "text": "enable mockingbird",
    "language": "en"
  }'

# Expected: {"status": "success", "intent": "mockingbird_enable"}

# Test 2: General question (fallback)
curl -X POST http://localhost:8000/api/webhooks/stt \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test123",
    "room_name": "room123",
    "text": "what is the capital of France",
    "language": "en"
  }'

# Expected: {"status": "success", "intent": "general_question"}
```

#### 3. Manual Testing Checklist
- [ ] Say "enable mockingbird" → Should activate immediately
- [ ] Say "what's your status" → Should report mockingbird state
- [ ] Say "disable mockingbird" → Should deactivate
- [ ] Say "hello" → Should give friendly greeting
- [ ] Ask random question → Should fall back to Gemini
- [ ] Check logs for intent classification results

### Phase 1 Success Metrics
- ✅ "enable mockingbird" activates skill 100% of the time
- ✅ Intent logged in webhook response
- ✅ No regression in general chat quality
- ✅ Latency remains <500ms

---

## PHASE 2: SKILL ORCHESTRATION LAYER

### Overview
Enhance SkillOrchestrator with confirmation flows, slot filling, and skill registry.

### 2.1 Add Confirmation Flow

**Modify `skill_orchestrator.py`:**

Add confirmation state tracking:
```python
from enum import Enum

class OrchestrationState(Enum):
    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_SLOTS = "awaiting_slots"
    EXECUTING = "executing"

class SkillOrchestrator:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = OrchestrationState.IDLE
        self.pending_intent = None
        self.pending_slots = {}
        # ... rest of init
```

Add confirmation logic for critical skills:
```python
CRITICAL_SKILLS = {
    "mockingbird_enable": "This will clone your voice. Are you sure?",
    "mockingbird_disable": "This will switch back to the default voice. Proceed?",
}

async def route_intent(self, ...):
    """Enhanced with confirmation flow"""

    # Check if we're awaiting confirmation
    if self.state == OrchestrationState.AWAITING_CONFIRMATION:
        return await self._handle_confirmation_response(processing_result)

    # Check if intent needs confirmation
    if intent in CRITICAL_SKILLS and confidence >= 0.7:
        # User didn't explicitly confirm, ask first
        if not self._is_confirmation_phrase(processing_result.original_text):
            self.state = OrchestrationState.AWAITING_CONFIRMATION
            self.pending_intent = intent

            return OrchestrationResult(
                handled=True,
                response=CRITICAL_SKILLS[intent],
                should_speak=True
            )

    # ... rest of routing logic

def _is_confirmation_phrase(self, text: str) -> bool:
    """Check if text is a confirmation"""
    affirmatives = ["yes", "yeah", "sure", "ok", "okay", "yep", "go ahead", "proceed"]
    text_lower = text.lower().strip()
    return any(affirm in text_lower for affirm in affirmatives)

async def _handle_confirmation_response(self, processing_result):
    """Handle user's response to confirmation prompt"""
    if self._is_confirmation_phrase(processing_result.original_text):
        # User confirmed - execute pending intent
        intent = self.pending_intent
        self.state = OrchestrationState.IDLE
        self.pending_intent = None

        # Execute the handler
        return await self.intent_handlers[intent](
            processing_result=processing_result,
            room_name=processing_result.context.current_room
        )
    else:
        # User declined
        self.state = OrchestrationState.IDLE
        self.pending_intent = None

        return OrchestrationResult(
            handled=True,
            response="Okay, I've canceled that. What would you like to do instead?"
        )
```

### 2.2 Add Slot Filling

**Example: Add voice style preference to mockingbird**

Modify intent definitions in `intent_classifier.py`:
```python
intents = {
    "mockingbird_enable": {
        "required_slots": [],  # No required slots
        "optional_slots": ["voice_style", "pitch_adjustment"],
        "trigger_phrases": [...]
    }
}
```

Modify slot extraction to ask for optional slots:
```python
async def _handle_mockingbird_enable(self, processing_result, room_name):
    """Enhanced with slot filling"""

    # Check for optional slots
    voice_style = processing_result.slots.get("voice_style")

    if not voice_style:
        # Ask user if they want to specify style
        return OrchestrationResult(
            handled=True,
            response="Activating mockingbird! Would you like any specific voice adjustments? You can say 'warmer', 'energetic', or 'as-is'.",
            should_speak=True
        )

    # Continue with voice style preference...
```

### 2.3 Add Skill Registry

**Create `app/services/skill_registry.py`:**
```python
"""
Skill Registry - Centralized skill management
"""
from typing import Dict, Callable, List, Optional
from dataclasses import dataclass
from enum import Enum

class SkillCategory(Enum):
    VOICE = "voice"
    INFORMATION = "information"
    CONTROL = "control"
    ENTERTAINMENT = "entertainment"

@dataclass
class SkillDefinition:
    """Definition of a skill"""
    name: str
    category: SkillCategory
    description: str
    intents: List[str]  # Intents that trigger this skill
    handler: Callable
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None

class SkillRegistry:
    """Central registry for all skills"""

    def __init__(self):
        self.skills: Dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition):
        """Register a skill"""
        self.skills[skill.name] = skill

    def get_skill_for_intent(self, intent: str) -> Optional[SkillDefinition]:
        """Get skill that handles given intent"""
        for skill in self.skills.values():
            if intent in skill.intents:
                return skill
        return None

    def list_skills(self, category: Optional[SkillCategory] = None) -> List[SkillDefinition]:
        """List all skills, optionally filtered by category"""
        if category:
            return [s for s in self.skills.values() if s.category == category]
        return list(self.skills.values())
```

**Modify `skill_orchestrator.py` to use registry:**
```python
def __init__(self, session_id: str):
    self.session_id = session_id
    self.registry = SkillRegistry()
    self.mockingbird = MockingbirdSkill()

    # Register skills
    self._register_skills()

def _register_skills(self):
    """Register all available skills"""

    # Mockingbird skill
    self.registry.register(SkillDefinition(
        name="mockingbird",
        category=SkillCategory.VOICE,
        description="Clone and use user's voice",
        intents=["mockingbird_enable", "mockingbird_disable", "mockingbird_status"],
        handler=self._handle_mockingbird,
        requires_confirmation=True,
        confirmation_message="This will clone your voice. Proceed?"
    ))

    # Add more skills here...

async def route_intent(self, ...):
    """Enhanced with skill registry"""

    # Look up skill for this intent
    skill = self.registry.get_skill_for_intent(intent)

    if skill:
        # Check if confirmation needed
        if skill.requires_confirmation and not self._awaiting_confirmation:
            return await self._request_confirmation(skill)

        # Execute skill handler
        return await skill.handler(processing_result, room_name)

    # Fall back to general chat...
```

### Phase 2 Testing

**Test confirmation flow:**
```python
# Test conversation:
User: "Enable mockingbird"
Bot: "This will clone your voice. Are you sure?"
User: "Yes"
Bot: "Activating mockingbird! Please speak for 8 seconds..."

# Test cancellation:
User: "Enable mockingbird"
Bot: "This will clone your voice. Are you sure?"
User: "No, never mind"
Bot: "Okay, I've canceled that. What would you like to do instead?"
```

### Phase 2 Success Metrics
- ✅ Critical skills require confirmation
- ✅ User can cancel operations
- ✅ Skill registry makes adding new skills easy
- ✅ Slot filling works for multi-turn dialogues

---

## PHASE 3: STATE-AWARE RESPONSE GENERATION

### Overview
Use dialogue states to make responses context-aware and natural.

### 3.1 Create Response Generator

**Create `app/services/response_generator.py`:**
```python
"""
Response Generator - Natural, context-aware responses
"""
from typing import Dict, Optional
from app.services.dialogue_state import DialogueState
from app.services.conversation_manager import ConversationContext

class ResponseGenerator:
    """
    Generates natural language responses based on:
    - Dialogue state
    - Conversation context
    - User preferences
    """

    def __init__(self):
        self.response_templates = self._load_templates()

    def generate(
        self,
        base_response: str,
        dialogue_state: DialogueState,
        context: ConversationContext,
        intent: str
    ) -> str:
        """
        Enhance base response with state-aware phrasing.

        Args:
            base_response: Base response text
            dialogue_state: Current dialogue state
            context: Conversation context
            intent: Intent being responded to

        Returns:
            Enhanced natural language response
        """

        # Add state-aware prefix
        prefix = self._get_state_prefix(dialogue_state, context)

        # Add personalization
        response = self._personalize(base_response, context)

        # Add continuity markers if in multi-turn conversation
        if context.turn_count > 1:
            response = self._add_continuity_markers(response, context)

        return f"{prefix}{response}" if prefix else response

    def _get_state_prefix(
        self,
        state: DialogueState,
        context: ConversationContext
    ) -> str:
        """Get natural prefix based on dialogue state"""

        if state == DialogueState.GREETING:
            time_of_day = self._get_time_of_day()
            return f"Good {time_of_day}! "

        elif state == DialogueState.CONFIRMATION:
            return "Just to confirm - "

        elif state == DialogueState.ERROR_RECOVERY:
            return "Sorry about that. "

        elif state == DialogueState.SLOT_FILLING:
            return "Got it. "

        return ""

    def _personalize(
        self,
        response: str,
        context: ConversationContext
    ) -> str:
        """Add personalization based on user profile"""

        user_name = context.user_profile.get("name")
        if user_name and "{name}" in response:
            response = response.replace("{name}", user_name)

        return response

    def _add_continuity_markers(
        self,
        response: str,
        context: ConversationContext
    ) -> str:
        """Add conversational continuity"""

        # Reference previous topic if relevant
        previous_topic = context.mentioned_entities.get("current_topic")

        # Add natural transitions
        transitions = [
            "Also, ",
            "By the way, ",
            "And ",
        ]

        # Randomly add transition if appropriate
        # (This is simplified - real implementation would be more sophisticated)

        return response

    def _get_time_of_day(self) -> str:
        """Get time-appropriate greeting"""
        from datetime import datetime
        hour = datetime.now().hour

        if hour < 12:
            return "morning"
        elif hour < 17:
            return "afternoon"
        else:
            return "evening"

    def _load_templates(self) -> Dict:
        """Load response templates for different situations"""
        return {
            "error": [
                "I'm having trouble with that. Could you try rephrasing?",
                "Sorry, I didn't quite catch that. Can you say that again?",
                "I'm not sure I understood. Could you explain differently?"
            ],
            "success": [
                "Done!",
                "All set!",
                "Got it!",
                "No problem!"
            ],
            # Add more templates...
        }
```

### 3.2 Integrate with Skill Orchestrator

**Modify `skill_orchestrator.py`:**
```python
from app.services.response_generator import ResponseGenerator

class SkillOrchestrator:
    def __init__(self, session_id: str):
        # ... existing init
        self.response_generator = ResponseGenerator()

    async def route_intent(self, ...):
        """Enhanced with natural response generation"""

        # ... existing routing logic

        # After getting result from handler
        if result.handled and result.response:
            # Enhance response with context
            enhanced_response = self.response_generator.generate(
                base_response=result.response,
                dialogue_state=processing_result.context.dialogue_state,
                context=processing_result.context,
                intent=processing_result.intent
            )

            # Update result with enhanced response
            result.response = enhanced_response

        # ... rest of method
```

### 3.3 Add Conversation Memory

**Modify `conversation_manager.py`:**

Add short-term memory:
```python
class ConversationContext:
    # ... existing fields

    recent_topics: List[str]  # Last 3-5 topics discussed
    pending_questions: List[str]  # Questions user asked but we haven't answered
    user_corrections: List[Dict]  # When user corrects something

def process_user_input(self, ...):
    """Enhanced with memory management"""

    # ... existing logic

    # Update recent topics
    self._update_topic_memory(classified_intent, extracted_slots)

    # Check for pending questions
    self._check_pending_questions(text)

    # ... rest of method

def _update_topic_memory(self, intent: str, slots: Dict):
    """Update conversation topic memory"""
    current_topic = self._extract_topic(intent, slots)

    if current_topic and current_topic != self.context.mentioned_entities.get("current_topic"):
        # Topic changed
        self.context.recent_topics.append(current_topic)
        self.context.recent_topics = self.context.recent_topics[-5:]  # Keep last 5
        self.context.mentioned_entities["current_topic"] = current_topic
```

### Phase 3 Testing

**Test state-aware responses:**
```python
# Test time-aware greetings
# Morning (8 AM):
User: "Hello"
Bot: "Good morning! How can I help you today?"

# Evening (8 PM):
User: "Hello"
Bot: "Good evening! How can I help you today?"

# Test continuity:
User: "What's the weather?"
Bot: "It's sunny and 75 degrees."
User: "And tomorrow?"
Bot: "Tomorrow will be partly cloudy with a high of 72."  # Uses "And" naturally

# Test error recovery:
User: "Activate the thingamajig"
Bot: "Sorry about that. I'm not sure what you're referring to. Could you clarify?"
```

### Phase 3 Success Metrics
- ✅ Responses feel contextual and natural
- ✅ Time-appropriate greetings
- ✅ Conversational continuity maintained
- ✅ Error recovery feels human-like

---

## CONFIGURATION CHANGES

### Update `config.py`

Add orchestration settings:
```python
class Settings(BaseSettings):
    # ... existing settings

    # Orchestration settings
    INTENT_CONFIDENCE_THRESHOLD: float = 0.7
    REQUIRE_CONFIRMATION_FOR_CRITICAL_SKILLS: bool = True
    ENABLE_SLOT_FILLING: bool = True
    ENABLE_STATE_AWARE_RESPONSES: bool = True

    # Conversation settings
    MAX_CONTEXT_WINDOW: int = 10  # Number of turns to keep
    ENABLE_CONVERSATION_MEMORY: bool = True

    class Config:
        env_file = "../../../config.env"
```

---

## ROLLBACK PLAN

### If Phase 1 Fails
1. Revert webhook changes in `webhooks.py`
2. Remove new files: `session_managers.py`, `skill_orchestrator.py`
3. Revert `simple_voice_assistant.py` changes
4. System returns to current behavior

### If Phase 2 Fails
1. Keep Phase 1 (intent classification works)
2. Remove confirmation logic from skill_orchestrator
3. Remove skill_registry.py
4. Skills still activate via intent classification, just without confirmation

### If Phase 3 Fails
1. Keep Phases 1 & 2
2. Remove response_generator.py
3. Use plain text responses
4. System still has reliable skill activation and confirmation

### Rollback Commands
```bash
# Full rollback
git checkout HEAD -- June/services/june-orchestrator/app/routes/webhooks.py
git checkout HEAD -- June/services/june-orchestrator/app/services/simple_voice_assistant.py
rm June/services/june-orchestrator/app/services/session_managers.py
rm June/services/june-orchestrator/app/services/skill_orchestrator.py
rm June/services/june-orchestrator/app/services/response_generator.py
rm June/services/june-orchestrator/app/services/skill_registry.py

# Restart service
docker-compose restart june-orchestrator
```

---

## TESTING STRATEGY

### 1. Development Testing (Local)
```bash
# Start services in test mode
docker-compose -f docker-compose.test.yml up

# Run unit tests
cd June/services/june-orchestrator
pytest tests/

# Run integration tests
pytest tests/integration/
```

### 2. Staging Testing
- Deploy to staging environment
- Run automated test suite
- Manual testing with test scripts
- Performance benchmarking

### 3. Production Deployment
- Deploy during low-traffic period
- Monitor logs for errors
- A/B testing: 10% → 50% → 100% traffic
- Rollback if error rate > 5%

### Test Scenarios

**Critical Path Tests:**
1. ✅ Mockingbird activation via "enable mockingbird"
2. ✅ Mockingbird deactivation via "disable mockingbird"
3. ✅ Status check via "is mockingbird on"
4. ✅ General questions fall back to Gemini correctly
5. ✅ Confirmation flow works for critical skills
6. ✅ User can cancel operations
7. ✅ Multi-turn conversations maintain context

**Edge Cases:**
1. User says ambiguous phrase
2. User interrupts during confirmation
3. User changes topic mid-flow
4. Network errors during skill execution
5. Mockingbird already active when user asks to enable
6. Multiple sessions with different states

---

## SUCCESS METRICS

### Technical Metrics
- **Skill Activation Rate:** >95% for explicit commands (e.g., "enable mockingbird")
- **Intent Classification Accuracy:** >90% for known intents
- **Latency:** Maintain <500ms for skill activation
- **Error Rate:** <2% (down from current rate)

### User Experience Metrics
- **Conversation Naturalness:** Qualitative assessment (user feedback)
- **Multi-turn Success Rate:** >80% for 3+ turn conversations
- **User Corrections:** <10% of interactions require clarification
- **Session Completion Rate:** >90% users complete intended action

### Monitoring
- Log intent classification results
- Track skill activation success/failure
- Measure response time at each stage
- Monitor Gemini fallback rate

---

## TIMELINE

### Phase 1: Intent Classification Integration
- **Implementation:** 2-3 hours
- **Testing:** 1-2 hours
- **Deployment:** 30 minutes
- **Total:** ~4-6 hours

### Phase 2: Skill Orchestration Layer
- **Implementation:** 3-4 hours
- **Testing:** 2 hours
- **Deployment:** 30 minutes
- **Total:** ~5-7 hours

### Phase 3: State-Aware Responses
- **Implementation:** 2-3 hours
- **Testing:** 1-2 hours
- **Deployment:** 30 minutes
- **Total:** ~3-6 hours

**Total Project Time:** 12-19 hours (1.5 to 2.5 days)

---

## RISKS & MITIGATIONS

### Risk 1: Latency Increase
**Impact:** High
**Probability:** Medium
**Mitigation:**
- Profile each component
- Optimize intent classification (use caching)
- Run classification in parallel with context retrieval
- Set timeout limits

### Risk 2: Intent Misclassification
**Impact:** Medium
**Probability:** Low
**Mitigation:**
- Start with high confidence threshold (0.7)
- Fall back to Gemini for low confidence
- Add user feedback mechanism ("Is this what you meant?")
- Continuously improve intent patterns based on logs

### Risk 3: Breaking Existing Functionality
**Impact:** High
**Probability:** Low
**Mitigation:**
- Comprehensive testing before deployment
- Feature flags for gradual rollout
- Rollback plan ready
- Monitor error rates closely

### Risk 4: State Management Complexity
**Impact:** Medium
**Probability:** Medium
**Mitigation:**
- Keep state machine simple in Phase 1
- Add complexity gradually in Phase 2/3
- Clear state transition logging
- State reset on session timeout

---

## FUTURE ENHANCEMENTS (Post-Implementation)

### Phase 4: Advanced Features
1. **Proactive Suggestions**
   - "You usually ask about weather at this time - would you like to know?"
   - Based on conversation history and patterns

2. **Multi-Skill Coordination**
   - Combine skills in single request
   - "Translate this to Spanish and email it to John"

3. **Learning from Corrections**
   - When user corrects interpretation, update intent patterns
   - Personalized intent classification

4. **Rich Context**
   - Integration with calendar, email, documents
   - "Schedule a meeting" → Check calendar availability

5. **Emotional Intelligence**
   - Detect user sentiment
   - Adjust response tone accordingly

### Phase 5: Additional Skills
1. **Timer/Reminder Skill**
2. **Note-taking Skill**
3. **Translation Skill**
4. **Calculation Skill**
5. **Weather Skill**
6. **Calendar Skill**

---

## APPENDIX A: File Changes Summary

### New Files
- `app/services/session_managers.py` (~80 lines)
- `app/services/skill_orchestrator.py` (~400 lines Phase 1, ~600 lines Phase 2)
- `app/services/skill_registry.py` (~150 lines, Phase 2)
- `app/services/response_generator.py` (~250 lines, Phase 3)
- `tests/test_skill_orchestrator.py` (~200 lines)
- `tests/integration/test_orchestration_flow.py` (~150 lines)

### Modified Files
- `app/routes/webhooks.py` (~30 lines changed)
- `app/services/simple_voice_assistant.py` (~50 lines changed)
- `app/config.py` (~15 lines added)

### Total Lines of Code
- **New:** ~1,230 lines
- **Modified:** ~95 lines
- **Total Impact:** ~1,325 lines

---

## APPENDIX B: Logging & Debugging

### Add Structured Logging

**In `skill_orchestrator.py`:**
```python
import logging
import json

logger = logging.getLogger(__name__)

# Log intent routing decisions
logger.info("Intent routing", extra={
    "session_id": session_id,
    "intent": intent,
    "confidence": confidence,
    "handler": handler_name,
    "processing_time_ms": elapsed_ms
})
```

### Debug Endpoint

**Add to `webhooks.py`:**
```python
@router.get("/debug/session/{session_id}")
async def debug_session(session_id: str):
    """Debug endpoint to inspect session state"""
    conv_manager = get_conversation_manager(session_id)
    orchestrator = get_skill_orchestrator(session_id)

    return {
        "session_id": session_id,
        "dialogue_state": conv_manager.context.dialogue_state,
        "orchestrator_state": orchestrator.state,
        "recent_intents": conv_manager.context.recent_topics,
        "pending_action": orchestrator.pending_intent,
        "conversation_history": conv_manager.get_recent_history(5)
    }
```

---

## APPENDIX C: Performance Optimization

### Intent Classification Caching
```python
from functools import lru_cache

class IntentClassifier:
    @lru_cache(maxsize=1000)
    def classify_cached(self, text: str, language: str):
        """Cached classification for common phrases"""
        return self.classify(text, language)
```

### Parallel Processing
```python
import asyncio

async def route_intent(self, ...):
    """Process multiple things in parallel"""

    # Run in parallel
    classification_task = asyncio.create_task(
        self.classify_intent(text)
    )
    context_task = asyncio.create_task(
        self.get_context(session_id)
    )

    intent, context = await asyncio.gather(
        classification_task,
        context_task
    )
```

---

## CONCLUSION

This implementation plan transforms your June orchestrator from a simple chatbot to a natural AI assistant by:

1. **Connecting existing components** - Your sophisticated intent classification and dialogue management already exist, they just need to be wired in
2. **Deterministic skill activation** - Rule-based intent matching ensures skills activate reliably
3. **Natural conversations** - State-aware responses and conversation memory make interactions feel contextual
4. **Incremental deployment** - Three phases allow testing and rollback at each step

The architecture leverages your existing work while adding the orchestration layer that ties everything together. Each phase is independently valuable:
- **Phase 1 alone** solves the skill activation problem
- **Phase 2** adds confirmation and safety
- **Phase 3** makes conversations feel natural

**Estimated effort:** 12-19 hours total, deployable in phases over 2-3 days.

**Next step:** Review this plan and approve proceeding to Phase 1 implementation.

---

**Questions or concerns about this plan?** Let me know and I'll address them before we begin implementation!
