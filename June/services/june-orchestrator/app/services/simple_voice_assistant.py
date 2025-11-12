"""
Simple Voice Assistant - FIXED VERSION (Loop Prevention)
Stops tool calling loop by not continuing LLM stream after tool execution
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
    
    def __init__(self, max_turns: int = 5):
        self.sessions: Dict[str, List[Message]] = {}
        self.max_turns = max_turns
        logger.info(f"✅ ConversationHistory initialized (max_turns={max_turns})")
    
    def add_message(self, session_id: str, role: str, content: str):
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
        if session_id not in self.sessions:
            return []
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
    
    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]


class SimpleVoiceAssistant:
    """Voice assistant with Mockingbird - FIXED tool loop prevention"""
    
    def __init__(
        self, 
        gemini_api_key: str, 
        tts_service,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str
    ):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=5)
        
        # Initialize Mockingbird skill
        self.mockingbird = MockingbirdSkill(
            tts_service=tts_service,
            livekit_url=livekit_url,
            livekit_api_key=livekit_api_key,
            livekit_api_secret=livekit_api_secret
        )
        
        # Natural speech settings
        self.max_sentence_chars = 180
        self.min_chunk_size = 50
        self.sentence_end = re.compile(r'[.!?。！？]+\s+')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0
        
        # Deduplication
        self._recent_transcripts: Dict[str, tuple[str, float]] = {}
        self._duplicate_window = 3.0
        
        # Processing locks
        self._processing_lock: Dict[str, asyncio.Lock] = {}
        
        self.ignore_partials = True
        
        logger.info("✅ Voice Assistant with Mockingbird initialized")
    
    def _is_duplicate_transcript(self, session_id: str, text: str) -> bool:
        """Check for duplicate transcripts"""
        current_time = time.time()
        
        # Clean up old entries
        expired = [
            sid for sid, (_, ts) in self._recent_transcripts.items()
            if current_time - ts > self._duplicate_window
        ]
        for sid in expired:
            del self._recent_transcripts[sid]
        
        # Check if duplicate
        if session_id in self._recent_transcripts:
            recent_text, recent_time = self._recent_transcripts[session_id]
            if recent_text == text and current_time - recent_time < self._duplicate_window:
                return True
        
        self._recent_transcripts[session_id] = (text, current_time)
        return False
    
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
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with tool instructions"""
        return """You are June, a warm and intelligent voice assistant with voice cloning capabilities.

🎯 PERSONALITY:
• Speak naturally and conversationally
• Be warm, helpful, and engaging
• Show appropriate emotion
• Use natural pauses and varied sentence length

🎭 MOCKINGBIRD VOICE CLONING:

CRITICAL: When you detect trigger phrases, IMMEDIATELY CALL THE FUNCTION ONCE.
Call it once and stop - do NOT call it multiple times.

TOOL 1: enable_mockingbird()
Triggers: "enable mockingbird", "clone my voice", "speak in my voice", "use my voice"
Action: CALL enable_mockingbird() ONCE → STOP

TOOL 2: disable_mockingbird()
Triggers: "disable mockingbird", "use your voice", "stop using my voice"
Action: CALL disable_mockingbird() ONCE → STOP

TOOL 3: check_mockingbird_status()
Triggers: "is mockingbird active", "what voice are you using", "mockingbird status"
Action: CALL check_mockingbird_status() ONCE → STOP

⚠️ CRITICAL RULES:
1. Call each function ONLY ONCE per request
2. After calling a function → STOP (don't call it again)
3. The function will handle all communication with the user
4. Do NOT generate any text after calling a function

NATURAL SPEECH (when NOT using tools):
• Write for voice: "Oh, that's interesting!" vs "That is interesting."
• Use commas for natural pauses
• Vary sentence length
• Show emotion when appropriate
• Sound like a real person
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
        
        # ✅ KEY FIX: Check if Mockingbird is busy FIRST
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
        
        # Ignore partials
        if is_partial and self.ignore_partials:
            return {"status": "skipped", "reason": "partial_ignored"}
        
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
        """Process transcript - FIXED to prevent tool loop"""
        
        word_count = len(text.strip().split())
        
        if word_count < 2:
            return {"status": "skipped", "reason": "too_short"}
        
        logger.info("=" * 80)
        logger.info(f"📥 Session: {session_id[:8]}...")
        logger.info(f"📝 Text: '{text}'")
        
        try:
            # Get conversation history
            history = self.history.get_history(session_id)
            
            # Get current voice
            current_voice_id = self.mockingbird.get_current_voice_id(session_id)
            logger.info(f"🎙️ Using voice: {current_voice_id}")
            
            # Build system prompt
            system_prompt = self._build_system_prompt()
            
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
                # ✅ Handle tool calls
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
                    
                    # ✅ CRITICAL: Stop processing immediately
                    # Don't continue the loop - tool handles everything
                    break
                
                # Handle text tokens (only if no tool was called)
                if not tool_executed and isinstance(chunk, str):
                    full_response += chunk
                    sentence_buffer += chunk
                    
                    # Extract complete sentences
                    sentence, sentence_buffer = self._extract_complete_sentence(sentence_buffer)
                    
                    if sentence:
                        sentence_count += 1
                        cleaned = self._clean_llm_output(sentence)
                        
                        if cleaned:
                            logger.info(f"🔊 Sentence #{sentence_count}: '{cleaned[:60]}...'")
                            await self._send_tts(room_name, cleaned, current_voice_id)
                            self.total_sentences_sent += 1
            
            # Send remaining text (only if no tool was called)
            if not tool_executed and sentence_buffer.strip():
                cleaned = self._clean_llm_output(sentence_buffer.strip())
                
                if cleaned and len(cleaned) >= self.min_chunk_size:
                    sentence_count += 1
                    logger.info(f"🔊 Final: '{cleaned[:50]}...'")
                    await self._send_tts(room_name, cleaned, current_voice_id)
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
    
    async def _stream_gemini(
        self,
        system_prompt: str,
        user_message: str,
        history: List[Dict]
    ) -> AsyncIterator:
        """
        Stream from Gemini with tool support
        
        ✅ FIXED: Only yields tool call once, then stops
        """
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
            
            # Configure generation with tools
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
            
            # Track if we've seen a tool call
            tool_call_seen = False
            
            # Stream response
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=full_prompt,
                config=config
            ):
                # Check for tool calls FIRST
                if hasattr(chunk, 'function_calls') and chunk.function_calls:
                    for func_call in chunk.function_calls:
                        if not tool_call_seen:
                            tool_call_seen = True
                            yield {
                                "type": "tool_call",
                                "tool_name": func_call.name,
                                "tool_args": dict(func_call.args) if func_call.args else {}
                            }
                            # ✅ CRITICAL: Return immediately after first tool call
                            # Don't process any more chunks
                            return
                
                # Only yield text if we haven't seen a tool call
                if not tool_call_seen and chunk.text:
                    yield chunk.text
                    
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
        """
        Execute Mockingbird tool
        
        ✅ Tools handle their own TTS - no return value needed
        """
        try:
            logger.info(f"🔧 Executing tool: {tool_name}")
            
            if tool_name == "enable_mockingbird":
                result = await self.mockingbird.enable(session_id, room_name)
                
                # Tool returns TTS message - send it
                if "tts_message" in result:
                    await self._send_tts(room_name, result["tts_message"], "default")
                
            elif tool_name == "disable_mockingbird":
                result = await self.mockingbird.disable(session_id)
                
                # Tool returns TTS message - send it
                if "tts_message" in result:
                    current_voice = self.mockingbird.get_current_voice_id(session_id)
                    await self._send_tts(room_name, result["tts_message"], current_voice)
                
            elif tool_name == "check_mockingbird_status":
                result = self.mockingbird.check_status(session_id)
                
                # Tool returns TTS message - send it
                if "tts_message" in result:
                    current_voice = self.mockingbird.get_current_voice_id(session_id)
                    await self._send_tts(room_name, result["tts_message"], current_voice)
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
        """Handle user interruption"""
        logger.info(f"🛑 User interrupted")
        return {"status": "interrupted"}
    
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
    
    async def health_check(self) -> Dict:
        """Health check"""
        return {
            "healthy": True,
            "assistant": "simple_voice_assistant",
            "mockingbird": self.mockingbird.get_stats(),
            "stats": self.get_stats()
        }