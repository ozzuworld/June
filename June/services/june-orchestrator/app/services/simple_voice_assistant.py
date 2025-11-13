"""
Simple Voice Assistant - FIXED VERSION
Fixes:
1. More restrictive tool triggering (reduce false positives)
2. Use cloned voice for "already active" messages
3. Better system prompt to prevent accidental tool calls
"""
import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, AsyncIterator, Any
from dataclasses import dataclass
from datetime import datetime

from .mockingbird_skill import MockingbirdSkill, MOCKINGBIRD_TOOLS

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Single conversation message"""
    role: str
    content: str
    timestamp: datetime


class ConversationHistory:
    """Simple in-memory conversation history"""
    
    def __init__(self, max_turns: int = 10):
        self.sessions: Dict[str, List[Message]] = {}
        self.max_turns = max_turns
        logger.info(f"✅ ConversationHistory initialized (max_turns={max_turns})")
    
    def add_message(self, session_id: str, role: str, content: str):
        """Add message to history"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        
        self.sessions[session_id].append(
            Message(role=role, content=content, timestamp=datetime.utcnow())
        )
        
        # Trim to max messages
        max_messages = self.max_turns * 2
        if len(self.sessions[session_id]) > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]
    
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history"""
        if session_id not in self.sessions:
            return []
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
    
    def clear_session(self, session_id: str):
        """Clear session history"""
        if session_id in self.sessions:
            del self.sessions[session_id]


class SimpleVoiceAssistant:
    """
    Voice assistant with Mockingbird skill
    
    FIXES:
    1. Better tool trigger detection (reduce false positives)
    2. Use cloned voice for "already active" messages
    3. Improved system prompt
    """
    
    def __init__(
        self, 
        gemini_api_key: str, 
        tts_service,
        conversation_manager,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str
    ):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.conversation_manager = conversation_manager
        self.history = ConversationHistory(max_turns=10)
        
        # Initialize Mockingbird skill with conversation_manager
        self.mockingbird = MockingbirdSkill(
            tts_service=tts_service,
            conversation_manager=conversation_manager,
            livekit_url=livekit_url,
            livekit_api_key=livekit_api_key,
            livekit_api_secret=livekit_api_secret
        )
        
        # Natural speech settings
        self.max_sentence_chars = 180
        self.min_chunk_size = 15  # ✅ FIX: Reduced from 50 to allow shorter responses
        self.sentence_end = re.compile(r'[.!?。！？]+\s+')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0

        # Deduplication
        self._recent_transcripts: Dict[str, tuple[str, float]] = {}
        self._duplicate_window = 30.0  # ✅ Increased from 3s to 30s to catch delayed duplicates from STT

        # Processing locks and task tracking
        self._processing_lock: Dict[str, asyncio.Lock] = {}
        self._processing_tasks: Dict[str, asyncio.Task] = {}
        self._interrupted_sessions: set = set()

        # Turn management - track when assistant is responding
        self._assistant_responding: Dict[str, bool] = {}
        self._last_response_time: Dict[str, float] = {}

        # Echo detection - track recent assistant responses to prevent feedback loops
        self._recent_assistant_responses: Dict[str, list[tuple[str, float]]] = {}
        self._echo_window = 30.0  # Check last 30 seconds of responses
        self._echo_similarity_threshold = 0.6  # 60% match = likely echo

        self.ignore_partials = True
        
        logger.info("✅ Voice Assistant with Mockingbird initialized")
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts (simple word overlap)"""
        # Normalize texts
        words1 = set(text1.lower().replace(',', '').replace('.', '').split())
        words2 = set(text2.lower().replace(',', '').replace('.', '').split())

        if not words1 or not words2:
            return 0.0

        # Calculate Jaccard similarity
        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union) if union else 0.0

    def _is_duplicate_transcript(self, session_id: str, text: str) -> bool:
        """Check for duplicate or very similar transcripts"""
        current_time = time.time()

        # Clean up old entries
        expired = [
            sid for sid, (_, ts) in self._recent_transcripts.items()
            if current_time - ts > self._duplicate_window
        ]
        for sid in expired:
            del self._recent_transcripts[sid]

        # Check if duplicate or very similar
        if session_id in self._recent_transcripts:
            recent_text, recent_time = self._recent_transcripts[session_id]
            time_diff = current_time - recent_time

            # If within duplicate window
            if time_diff < self._duplicate_window:
                # Exact match
                if recent_text == text:
                    logger.info(f"🔁 Exact duplicate detected: '{text[:30]}...'")
                    return True

                # Similar match (80% similarity threshold)
                similarity = self._calculate_similarity(recent_text, text)
                if similarity >= 0.8:
                    logger.info(
                        f"🔁 Similar transcript detected ({similarity:.0%} match): "
                        f"'{text[:30]}...' vs '{recent_text[:30]}...'"
                    )
                    return True

        self._recent_transcripts[session_id] = (text, current_time)
        return False

    def _is_echo(self, session_id: str, text: str) -> bool:
        """Check if transcript is likely an echo of assistant's own voice"""
        current_time = time.time()

        # Get recent assistant responses for this session
        if session_id not in self._recent_assistant_responses:
            return False

        recent_responses = self._recent_assistant_responses[session_id]

        # Clean up old responses (older than echo_window)
        recent_responses = [
            (resp, timestamp)
            for resp, timestamp in recent_responses
            if current_time - timestamp < self._echo_window
        ]
        self._recent_assistant_responses[session_id] = recent_responses

        # Check similarity with recent responses
        for response_text, timestamp in recent_responses:
            similarity = self._calculate_similarity(text, response_text)

            if similarity >= self._echo_similarity_threshold:
                logger.warning(
                    f"🔊 ECHO DETECTED ({similarity:.0%} match): "
                    f"User transcript '{text[:50]}...' matches recent assistant response"
                )
                return True

        return False

    def _track_assistant_response(self, session_id: str, text: str):
        """Track assistant's response to detect echoes later"""
        current_time = time.time()

        if session_id not in self._recent_assistant_responses:
            self._recent_assistant_responses[session_id] = []

        self._recent_assistant_responses[session_id].append((text, current_time))

        # Keep only last 10 responses per session
        if len(self._recent_assistant_responses[session_id]) > 10:
            self._recent_assistant_responses[session_id] = self._recent_assistant_responses[session_id][-10:]

    def _clean_llm_output(self, text: str) -> str:
        """Clean LLM output for TTS"""
        # Remove leading "June:" or "Assistant:"
        text = re.sub(r'^(June\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        text = re.sub(r'^(Assistant\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Add space after punctuation if missing
        text = re.sub(r'([.!?,;:])([A-Za-z])', r'\1 \2', text)
        
        return text.strip()
    
    def _extract_complete_sentence(self, text_buffer: str) -> tuple[str, str]:
        """Extract complete sentence from buffer"""
        if len(text_buffer) < self.min_chunk_size:
            return "", text_buffer
        
        # Look for sentence ending
        match = self.sentence_end.search(text_buffer)
        
        if match:
            sentence = text_buffer[:match.end()].strip()
            remaining = text_buffer[match.end():].strip()
            
            if len(sentence) >= self.min_chunk_size:
                return sentence, remaining
        
        # If buffer is too long, force a break at natural pause
        if len(text_buffer) >= self.max_sentence_chars:
            # Find last comma or semicolon
            for char in [', ', '; ', ': ']:
                last_idx = text_buffer.rfind(char)
                if last_idx > self.min_chunk_size:
                    sentence = text_buffer[:last_idx + len(char)].strip()
                    remaining = text_buffer[last_idx + len(char):].strip()
                    return sentence, remaining
        
        return "", text_buffer
    
    def _should_enable_tools(self, text: str) -> bool:
        """Check if user message contains Mockingbird-related keywords"""
        text_lower = text.lower()
        keywords = [
            'mockingbird',
            'clone my voice',
            'clone voice',
            'use my voice',
            'use your voice',
            'voice cloning',
            'what voice are you using',
            'which voice',
            'voice status'
        ]
        return any(keyword in text_lower for keyword in keywords)

    def _build_system_prompt(self, conversation_style: str = "balanced") -> str:
        """
        Build system prompt with tool instructions and conversation style

        Args:
            conversation_style: "casual", "formal", "balanced", or "technical"
        """
        # Style-specific personality prompts
        style_prompts = {
            "casual": """🎯 PERSONALITY & STYLE:
• Speak in a friendly, relaxed, conversational tone
• Use contractions freely (I'm, you're, let's, etc.)
• Keep responses brief and to the point
• Sound like you're chatting with a friend
• Use casual expressions and phrases
• Be warm and approachable""",

            "formal": """🎯 PERSONALITY & STYLE:
• Speak in a professional, polite, and articulate manner
• Use complete sentences without contractions
• Be thorough and precise in your responses
• Maintain a respectful and courteous tone
• Use proper grammar and formal language
• Be helpful while maintaining professionalism""",

            "technical": """🎯 PERSONALITY & STYLE:
• Speak with technical precision and expertise
• Use appropriate technical terminology
• Provide detailed, accurate explanations
• Be specific and thorough in responses
• Show depth of knowledge when relevant
• Balance technical detail with clarity""",

            "balanced": """🎯 PERSONALITY & STYLE:
• Speak naturally and conversationally
• Be warm, helpful, and engaging
• Show appropriate emotion
• Use natural pauses and varied sentence length
• Adapt your tone to match the context"""
        }

        # Get the appropriate style prompt (default to balanced if unknown)
        personality_section = style_prompts.get(conversation_style, style_prompts["balanced"])

        return f"""You are June, a warm and intelligent voice assistant with voice cloning capabilities.

{personality_section}

🎭 MOCKINGBIRD VOICE CLONING:

⚠️ CRITICAL: ONLY call these tools when user EXPLICITLY asks for them!

TOOL 1: enable_mockingbird()
ONLY call when user says EXACTLY:
- "enable mockingbird"
- "turn on mockingbird"
- "activate mockingbird"
- "clone my voice"
- "use my voice"
DO NOT call for: normal conversation, questions, unrelated commands

TOOL 2: disable_mockingbird()
ONLY call when user says EXACTLY:
- "disable mockingbird"
- "turn off mockingbird"
- "deactivate mockingbird"
- "use your voice"
- "stop using my voice"
DO NOT call for: normal conversation, questions, unrelated commands

TOOL 3: check_mockingbird_status()
ONLY call when user says EXACTLY:
- "is mockingbird active"
- "mockingbird status"
- "what voice are you using"
- "are you using my voice"
DO NOT call for: normal conversation, questions, mentions of voice

⚠️ CRITICAL RULES:
1. Be VERY conservative - don't call tools unless user explicitly requests them
2. If user just mentions "voice" or "mockingbird" in conversation, respond normally (NO TOOL)
3. Call each function ONLY ONCE per request
4. After calling a function → STOP (don't call it again)
5. The function will handle all communication with the user
6. Do NOT generate any text after calling a function

EXAMPLES OF WHEN NOT TO CALL TOOLS:
❌ "your voice else I can doubt" → Normal response (no tool)
❌ "I like your voice" → Normal response (no tool)
❌ "Ready to clone your voice..." → Normal response (this is TTS echo, no tool)
❌ "can you hear my voice" → Normal response (no tool)

EXAMPLES OF WHEN TO CALL TOOLS:
✅ "enable mockingbird" → Call enable_mockingbird()
✅ "turn on mockingbird" → Call enable_mockingbird()
✅ "disable mockingbird" → Call disable_mockingbird()

NATURAL SPEECH (when NOT using tools):
• Write for voice: "Oh, that's interesting!" vs "That is interesting."
• Use commas for natural pauses
• Vary sentence length
• Show emotion when appropriate
• Sound like a real person talking
"""
    
    async def handle_transcript(
        self,
        session_id: str,
        room_name: str,
        text: str,
        is_partial: bool = False,
        audio_data: Optional[bytes] = None
    ) -> Dict:
        """Main entry point for STT transcripts"""
        start_time = time.time()
        self.total_requests += 1
        
        # Check if Mockingbird is busy
        state = self.mockingbird.get_session_state(session_id)
        if state.is_busy():
            logger.info(
                f"🎤 Mockingbird is {state.state} - ignoring transcript: '{text[:30]}...'"
            )
            return {
                "status": "mockingbird_busy",
                "state": state.state,
                "message": "Recording/processing voice sample"
            }

        # Turn management: Check if assistant is still responding
        if self._assistant_responding.get(session_id, False):
            current_time = time.time()
            last_time = self._last_response_time.get(session_id, 0)
            time_since_response = current_time - last_time

            # If assistant responded recently (within 0.5 seconds), skip
            # Reduced from 1.5s to 0.5s for more natural conversation flow
            if time_since_response < 0.5:
                logger.info(
                    f"🔇 Assistant still responding ({time_since_response:.1f}s ago) - "
                    f"ignoring new input: '{text[:30]}...'"
                )
                return {"status": "skipped", "reason": "assistant_turn"}

        # Ignore partials
        if is_partial and self.ignore_partials:
            return {"status": "skipped", "reason": "partial_ignored"}

        # Check for echo (assistant's own voice being transcribed)
        if self._is_echo(session_id, text):
            logger.info(f"🔊 Echo detected - ignoring: '{text[:50]}...'")
            return {"status": "skipped", "reason": "echo"}

        # Check for duplicates
        if self._is_duplicate_transcript(session_id, text):
            return {"status": "skipped", "reason": "duplicate"}
        
        # Get processing lock
        if session_id not in self._processing_lock:
            self._processing_lock[session_id] = asyncio.Lock()
        
        lock = self._processing_lock[session_id]
        
        # Skip if already processing short input
        word_count = len(text.strip().split())
        if lock.locked() and word_count < 5:
            return {"status": "skipped", "reason": "already_processing"}
        
        async with lock:
            return await self._process_transcript(
                session_id=session_id,
                room_name=room_name,
                text=text,
                is_partial=is_partial,
                start_time=start_time
            )
    
    async def _process_transcript(
        self,
        session_id: str,
        room_name: str,
        text: str,
        is_partial: bool,
        start_time: float
    ) -> Dict:
        """Process transcript"""

        word_count = len(text.strip().split())

        if word_count < 2:
            return {"status": "skipped", "reason": "too_short"}

        logger.info("=" * 80)
        logger.info(f"📥 Session: {session_id[:8]}...")
        logger.info(f"📝 Text: '{text}'")

        # Mark that assistant is now responding
        self._assistant_responding[session_id] = True

        try:
            # Get conversation history
            history = self.history.get_history(session_id)
            
            # Get current voice
            current_voice_id = self.mockingbird.get_current_voice_id(session_id)
            logger.info(f"🎤 Using voice: {current_voice_id}")

            # Get conversation style from context
            conversation_style = "balanced"  # Default
            try:
                context = self.conversation_manager.get_context(room_name, session_id)
                if context:
                    conversation_style = context.conversation_style
                    logger.info(f"💬 Using conversation style: {conversation_style}")
            except Exception as e:
                logger.debug(f"Could not get conversation style, using default: {e}")

            # Build system prompt with conversation style
            system_prompt = self._build_system_prompt(conversation_style=conversation_style)
            
            # Stream from LLM with tool support
            full_response = ""
            sentence_buffer = ""
            sentence_count = 0
            tool_executed = False
            tool_name = None
            
            logger.info(f"🧠 Starting LLM stream...")
            
            async for chunk in self._stream_gemini(
                system_prompt=system_prompt,
                user_message=text,
                history=history
            ):
                logger.info(f"🔄 CONSUMER received chunk: type={type(chunk).__name__}, is_str={isinstance(chunk, str)}, is_dict={isinstance(chunk, dict)}")

                # Check for interruption
                if session_id in self._interrupted_sessions:
                    logger.info(f"🛑 Interruption detected - stopping LLM stream")
                    self._interrupted_sessions.discard(session_id)
                    return {
                        "status": "interrupted",
                        "message": "Processing stopped due to user interruption"
                    }

                # Handle tool calls and break immediately
                if isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_name = chunk['tool_name']
                    logger.info(f"🔧 Tool called: {tool_name}")

                    # Execute tool ONCE
                    await self._execute_tool(
                        tool_name=tool_name,
                        tool_args=chunk["tool_args"],
                        session_id=session_id,
                        room_name=room_name
                    )

                    tool_executed = True
                    break

                # Handle text tokens (only if no tool was called)
                if not tool_executed and isinstance(chunk, str):
                    logger.info(f"📝 Processing text chunk: '{chunk[:50]}', tool_executed={tool_executed}")
                    full_response += chunk
                    sentence_buffer += chunk
                    logger.info(f"📊 Buffer state: full_response_len={len(full_response)}, sentence_buffer='{sentence_buffer[:50]}'")

                    # Extract complete sentences
                    sentence, sentence_buffer = self._extract_complete_sentence(sentence_buffer)
                    logger.info(f"📐 Extracted: sentence='{sentence}', remaining_buffer='{sentence_buffer[:30]}'")

                    if sentence:
                        # Check for interruption before sending TTS
                        if session_id in self._interrupted_sessions:
                            logger.info(f"🛑 Interruption detected - stopping before TTS")
                            self._interrupted_sessions.discard(session_id)
                            return {
                                "status": "interrupted",
                                "message": "Processing stopped due to user interruption"
                            }

                        sentence_count += 1
                        cleaned = self._clean_llm_output(sentence)

                        if cleaned:
                            logger.info(f"🔊 Sentence #{sentence_count}: '{cleaned[:60]}...'")
                            await self._send_tts(room_name, cleaned, current_voice_id)
                            self._last_response_time[session_id] = time.time()
                            self.total_sentences_sent += 1
            
            # Send remaining text (only if no tool was called)
            if not tool_executed and sentence_buffer.strip():
                cleaned = self._clean_llm_output(sentence_buffer.strip())
                
                if cleaned and len(cleaned) >= self.min_chunk_size:
                    sentence_count += 1
                    logger.info(f"🔊 Final: '{cleaned[:50]}...'")
                    await self._send_tts(room_name, cleaned, current_voice_id)
                    self._last_response_time[session_id] = time.time()
                    self.total_sentences_sent += 1
            
            # Add to history
            if not is_partial:
                logger.info(f"💾 Adding to history...")
                self.history.add_message(session_id, "user", text)
                
                if tool_executed:
                    # Tool was called - store tool info
                    self.history.add_message(
                        session_id, 
                        "assistant", 
                        f"[Used tool: {tool_name}]"
                    )
                elif full_response:
                    # Normal response
                    self.history.add_message(session_id, "assistant", full_response)
                    # Track response for echo detection
                    self._track_assistant_response(session_id, full_response)

                logger.info(f"✅ History updated: now {len(self.history.get_history(session_id))} messages")
            
            total_time = (time.time() - start_time) * 1000
            
            logger.info("─" * 80)
            logger.info(f"✅ SUCCESS - Total: {total_time:.0f}ms")
            if tool_executed:
                logger.info(f"   Tool: {tool_name}")
            logger.info("=" * 80)
            
            return {
                "status": "success",
                "response": full_response or f"[Tool: {tool_name}]" if tool_executed else "[No response]",
                "sentences_sent": sentence_count,
                "tool_used": tool_executed,
                "voice_id": current_voice_id,
                "total_time_ms": total_time
            }
            
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)

            # Send error message
            try:
                await self._send_tts(room_name, "Sorry, I'm having trouble right now.", "default")
            except:
                pass

            return {"status": "error", "error": str(e)}

        finally:
            # Clear responding flag - assistant's turn is over
            self._assistant_responding[session_id] = False
            logger.info(f"✅ Assistant turn complete for {session_id[:8]}...")
    
    async def _stream_gemini(
        self,
        system_prompt: str,
        user_message: str,
        history: List[Dict]
    ) -> AsyncIterator:
        """Stream from Gemini with tool support"""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)

            # Build prompt with history
            if history:
                context_lines = [f"{msg['role']}: {msg['content']}" for msg in history]
                context = "\n".join(context_lines)
                full_prompt = (
                    f"{system_prompt}\n\n"
                    f"=== Recent Conversation ===\n{context}\n\n"
                    f"=== Current Message ===\n"
                    f"User: {user_message}\n\n"
                    f"Your response:"
                )
            else:
                full_prompt = f"{system_prompt}\n\nUser: {user_message}\n\nYour response:"

            # Only enable tools if user mentions Mockingbird-related keywords
            enable_tools = self._should_enable_tools(user_message)

            # Configure generation
            if enable_tools:
                logger.info("🔧 Tools ENABLED - Mockingbird keywords detected")
                config = types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=500,
                    top_p=0.95,
                    top_k=50,
                    tools=MOCKINGBIRD_TOOLS,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode='AUTO'
                        )
                    )
                )
            else:
                logger.info("💬 Tools DISABLED - Normal conversation mode")
                config = types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=500,
                    top_p=0.95,
                    top_k=50
                )
            
            # Track if we've seen a tool call
            tool_call_seen = False
            chunk_count = 0

            # Stream response
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=full_prompt,
                config=config
            ):
                chunk_count += 1
                logger.info(f"📦 Chunk #{chunk_count}: has_text={hasattr(chunk, 'text')}, text='{getattr(chunk, 'text', '')[:50]}', has_function_calls={hasattr(chunk, 'function_calls') and bool(getattr(chunk, 'function_calls', []))}")

                # Check for tool calls FIRST
                if hasattr(chunk, 'function_calls') and chunk.function_calls:
                    for func_call in chunk.function_calls:
                        if not tool_call_seen:
                            tool_call_seen = True
                            logger.info(f"🔧 Function call detected in chunk: {func_call.name}")
                            yield {
                                "type": "tool_call",
                                "tool_name": func_call.name,
                                "tool_args": dict(func_call.args) if func_call.args else {}
                            }
                            return

                # Only yield text if we haven't seen a tool call
                if not tool_call_seen and chunk.text:
                    logger.info(f"📝 Yielding text chunk: '{chunk.text[:50]}'")
                    yield chunk.text
                    # ✅ FIX: Yield control back to event loop after each chunk
                    await asyncio.sleep(0)

            logger.info(f"✅ Stream complete: {chunk_count} chunks processed, tool_call_seen={tool_call_seen}")
                    
        except Exception as e:
            logger.error(f"❌ Gemini error: {e}")
            yield "I'm having technical difficulties."
    
    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str,
        room_name: str
    ) -> None:
        """Execute Mockingbird tool - ✅ FIX: Use cloned voice for responses"""
        try:
            logger.info(f"🔧 Executing tool: {tool_name}")
            
            # ✅ FIX: Get current voice BEFORE calling tool
            current_voice = self.mockingbird.get_current_voice_id(session_id)
            
            if tool_name == "enable_mockingbird":
                result = await self.mockingbird.enable(session_id, room_name)
                
                # Tool returns TTS message - send it
                if "tts_message" in result:
                    # ✅ FIX: For "already active" message, use cloned voice
                    voice_to_use = "default" if result["status"] == "awaiting_sample" else current_voice
                    await self._send_tts(room_name, result["tts_message"], voice_to_use)
                
            elif tool_name == "disable_mockingbird":
                result = await self.mockingbird.disable(session_id)
                
                # Tool returns TTS message - send it with current voice
                if "tts_message" in result:
                    await self._send_tts(room_name, result["tts_message"], current_voice)
                
            elif tool_name == "check_mockingbird_status":
                result = self.mockingbird.check_status(session_id)

                # Tool returns TTS message - send it with the voice_id from result
                if "tts_message" in result:
                    await self._send_tts(room_name, result["tts_message"], result.get("voice_id", "default"))
            else:
                logger.error(f"❌ Unknown tool: {tool_name}")
                
        except Exception as e:
            logger.error(f"❌ Tool execution error: {e}", exc_info=True)
    
    async def _send_tts(self, room_name: str, text: str, voice_id: str):
        """Send text to TTS service"""
        try:
            await self.tts.publish_to_room(
                room_name=room_name,
                text=text,
                voice_id=voice_id,
                streaming=True
            )
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")
    
    async def handle_interruption(self, session_id: str, room_name: str):
        """Handle user interruption - stop ongoing processing and TTS"""
        logger.info(f"🛑 User interruption for session {session_id[:8]}... in room {room_name}")

        # Mark session as interrupted
        self._interrupted_sessions.add(session_id)

        # Cancel any ongoing processing task
        if session_id in self._processing_tasks:
            task = self._processing_tasks[session_id]
            if not task.done():
                logger.info(f"🛑 Cancelling ongoing processing task for {session_id[:8]}...")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"✅ Task cancelled successfully")
            del self._processing_tasks[session_id]

        # Note: We cannot easily stop ongoing TTS playback in LiveKit from here
        # The TTS request has already been sent to the XTTS service
        # The interruption will prevent NEW TTS from being sent

        logger.info(f"✅ Interruption handled - new processing will be prevented")

        return {
            "status": "interrupted",
            "message": "Processing stopped, ready for new input"
        }
    
    def get_stats(self) -> Dict:
        """Get statistics"""
        return {
            "mode": "natural_speech_with_mockingbird",
            "active_sessions": len(self.history.sessions),
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "mockingbird": self.mockingbird.get_stats()
        }
    
    def clear_session(self, session_id: str):
        """Clear session data"""
        self.history.clear_session(session_id)

        if session_id in self._recent_transcripts:
            del self._recent_transcripts[session_id]
        if session_id in self._processing_lock:
            del self._processing_lock[session_id]
        if session_id in self._processing_tasks:
            del self._processing_tasks[session_id]
        if session_id in self._assistant_responding:
            del self._assistant_responding[session_id]
        if session_id in self._last_response_time:
            del self._last_response_time[session_id]
        self._interrupted_sessions.discard(session_id)
    
    async def health_check(self) -> Dict:
        """Health check"""
        return {
            "healthy": True,
            "assistant": "simple_voice_assistant",
            "mockingbird": self.mockingbird.get_stats(),
            "stats": self.get_stats()
        }