"""
Simple Voice Assistant with Mockingbird Voice Cloning Skill
Natural speech + MCP-compatible tool calling + NEW SDK
"""
import asyncio
import logging
import re
import time
import json
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
            logger.info(f"🆕 Created new conversation for session {session_id[:8]}...")
        
        self.sessions[session_id].append(
            Message(role=role, content=content, timestamp=datetime.utcnow())
        )
        
        max_messages = self.max_turns * 2
        before_count = len(self.sessions[session_id])
        
        if before_count > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]
            logger.info(f"🗑️ Trimmed history for {session_id[:8]}...: {before_count} → {len(self.sessions[session_id])} messages")
    
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self.sessions:
            return []
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
    
    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            msg_count = len(self.sessions[session_id])
            del self.sessions[session_id]
            logger.info(f"🗑️ Cleared {msg_count} messages for session {session_id[:8]}...")


class SimpleVoiceAssistant:
    """
    Voice assistant with Mockingbird voice cloning skill
    MCP-compatible tool calling with natural speech
    """
    
    def __init__(self, gemini_api_key: str, tts_service):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=5)
        
        # Initialize Mockingbird skill
        self.mockingbird = MockingbirdSkill(tts_service)
        
        # Natural speech settings
        self.max_sentence_chars = 180
        self.min_chunk_size = 50
        self.sentence_end = re.compile(r'[.!?。！？]+\s+')
        self.natural_pause_markers = re.compile(r'[,;:—]\s+')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0
        self.avg_first_sentence_ms = 0
        self.mockingbird_activations = 0
        
        # TTS pacing
        self._last_tts_time: Dict[str, float] = {}
        self._natural_pause_duration = 0.6
        
        # Deduplication
        self._recent_transcripts: Dict[str, tuple[str, float]] = {}
        self._duplicate_window = 3.0
        
        # Processing locks
        self._processing_lock: Dict[str, asyncio.Lock] = {}
        
        self.ignore_partials = True
        
        logger.info("=" * 80)
        logger.info("✅ Voice Assistant with Mockingbird initialized")
        logger.info("   - Natural speech mode enabled")
        logger.info("   - Mockingbird voice cloning ready")
        logger.info("   - MCP-compatible tool calling")
        logger.info("   - NEW google-genai SDK")
        logger.info("=" * 80)
    
    def _is_duplicate_transcript(self, session_id: str, text: str) -> bool:
        """Check for duplicate transcripts"""
        current_time = time.time()
        
        expired = [
            sid for sid, (_, ts) in self._recent_transcripts.items()
            if current_time - ts > self._duplicate_window
        ]
        for sid in expired:
            del self._recent_transcripts[sid]
        
        if session_id in self._recent_transcripts:
            recent_text, recent_time = self._recent_transcripts[session_id]
            if recent_text == text and current_time - recent_time < self._duplicate_window:
                logger.warning(f"⚠️ Duplicate detected: '{text[:30]}...'")
                return True
        
        self._recent_transcripts[session_id] = (text, current_time)
        return False
    
    def _clean_llm_output(self, text: str) -> str:
        """Clean LLM output"""
        text = re.sub(r'^(June\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        text = re.sub(r'^(Assistant\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'([.!?,;:])([A-Za-z])', r'\1 \2', text)
        return text.strip()
    
    def _add_prosody_hints(self, text: str) -> str:
        """Add prosody hints"""
        text = re.sub(r'\s+(but|however|although|though)\s+', r', \1 ', text, flags=re.IGNORECASE)
        text = re.sub(r'^(Well|So|Now|Actually|In fact|By the way),?\s+', r'\1, ', text, flags=re.IGNORECASE)
        return text
    
    def _extract_complete_sentence(self, text_buffer: str) -> tuple[str, str]:
        """Extract complete sentence from buffer"""
        if len(text_buffer) < self.min_chunk_size:
            return "", text_buffer
        
        match = self.sentence_end.search(text_buffer)
        
        if match:
            sentence = text_buffer[:match.end()].strip()
            remaining = text_buffer[match.end():].strip()
            
            if len(sentence) >= self.min_chunk_size:
                return sentence, remaining
        
        if len(text_buffer) >= self.max_sentence_chars:
            pause_matches = list(self.natural_pause_markers.finditer(text_buffer))
            
            if pause_matches:
                for match in reversed(pause_matches):
                    if match.end() >= self.min_chunk_size:
                        sentence = text_buffer[:match.end()].strip()
                        remaining = text_buffer[match.end():].strip()
                        return sentence, remaining
        
        return "", text_buffer
    
    def _build_system_prompt_with_tools(self) -> str:
        """Build system prompt with tool awareness"""
        return """You are June, a warm and intelligent voice assistant with voice cloning capabilities.

🎯 CORE PERSONALITY:
• Speak naturally and conversationally (your responses are spoken aloud)
• Be warm, helpful, and engaging
• Show appropriate emotion and enthusiasm
• Use natural pauses, varied sentence length

🎭 MOCKINGBIRD VOICE CLONING - CRITICAL TOOL USAGE:
You have THREE tools that you MUST use when appropriate:

1. enable_mockingbird - CALL THIS IMMEDIATELY when user says:
   - "enable mockingbird"
   - "activate mockingbird"
   - "clone my voice"
   - "speak in my voice"
   DO NOT just talk about it - CALL THE TOOL!

2. disable_mockingbird - CALL THIS IMMEDIATELY when user says:
   - "disable mockingbird"
   - "deactivate mockingbird"
   - "use your voice"
   - "stop using my voice"
   DO NOT just talk about it - CALL THE TOOL!

3. check_mockingbird_status - CALL THIS when user asks:
   - "is mockingbird active?"
   - "what voice are you using?"
   DO NOT just answer - CALL THE TOOL to get accurate status!

⚠️ IMPORTANT: When user requests mockingbird activation/deactivation, you MUST call the tool.
DO NOT explain what you're going to do - ACTUALLY DO IT by calling the tool!

NATURAL SPEECH RULES:
• Write for voice: "Oh, that's interesting!" vs "That is interesting."
• Use commas for natural pauses
• Vary sentence length (short AND long)
• Show emotion when appropriate
• Sound like a real person having a conversation

❌ AVOID:
• Lists or bullet points
• Formal language ("Furthermore", "Additionally")
• Robotic phrasing
• Monotone delivery
• Talking about using tools instead of actually using them!"""
    
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
        
        # Check if Mockingbird is capturing audio
        if self.mockingbird.is_active(session_id):
            mockingbird_state = self.mockingbird.get_session_state(session_id)
            
            if mockingbird_state["state"] in ["awaiting_voice_sample", "capturing_audio"]:
                logger.info(f"🎤 Mockingbird capturing audio from '{text[:30]}...'")
                
                # Let mockingbird process the audio
                capture_result = await self.mockingbird.process_transcript_chunk(
                    session_id=session_id,
                    text=text,
                    audio_data=audio_data
                )
                
                if capture_result.get("status") == "ready_to_clone":
                    # Got enough audio - respond naturally
                    response_text = capture_result.get("message", "Processing your voice...")
                    await self._send_to_tts_natural(
                        room_name=room_name,
                        text=response_text,
                        session_id=session_id,
                        voice_id="default"  # Use default while processing
                    )
                
                return {
                    "status": "mockingbird_capturing",
                    "capture_result": capture_result
                }
        
        # Ignore partials
        if is_partial and self.ignore_partials:
            logger.debug(f"⏸️ Ignoring partial: '{text[:50]}...'")
            return {"status": "skipped", "reason": "partial_ignored"}
        
        # Check for duplicates
        if self._is_duplicate_transcript(session_id, text):
            return {"status": "skipped", "reason": "duplicate"}
        
        # Get processing lock
        if session_id not in self._processing_lock:
            self._processing_lock[session_id] = asyncio.Lock()
        
        lock = self._processing_lock[session_id]
        word_count = len(text.strip().split())
        
        if lock.locked():
            if word_count < 5:
                logger.warning(f"⚠️ Already processing, skipping short input: '{text}'")
                return {"status": "skipped", "reason": "already_processing"}
            else:
                logger.info(f"🛑 User interrupting with new request: '{text[:50]}...'")
        
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
        """Process transcript with tool calling support"""
        
        word_count = len(text.strip().split())
        
        if word_count < 2:
            logger.debug(f"⏸️ Text too short: '{text}' ({word_count} words)")
            return {"status": "skipped", "reason": "too_short"}
        
        logger.info("=" * 80)
        logger.info(f"📥 Session: {session_id[:8]}")
        logger.info(f"📝 Text: '{text}'")
        logger.info(f"📊 Words: {word_count}")
        
        try:
            # Get history
            history = self.history.get_history(session_id)
            logger.info(f"📚 History: {len(history)} messages")
            
            # Build prompt
            system_prompt = self._build_system_prompt_with_tools()
            
            # Stream LLM response with tool support
            full_response = ""
            sentence_buffer = ""
            sentence_count = 0
            first_sentence_time = None
            tool_calls_made = []
            
            # Get current voice (might be cloned)
            current_voice_id = self.mockingbird.get_current_voice_id(session_id)
            
            logger.info(f"🎙️ Using voice: {current_voice_id}")
            logger.info(f"🧠 Starting LLM stream with tool support...")
            llm_start = time.time()
            
            async for chunk in self._stream_gemini_with_tools(
                system_prompt=system_prompt,
                user_message=text,
                history=history,
                session_id=session_id
            ):
                # Handle tool calls
                if isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_result = await self._execute_tool(
                        tool_name=chunk["tool_name"],
                        tool_args=chunk["tool_args"],
                        session_id=session_id,
                        room_name=room_name
                    )
                    tool_calls_made.append({
                        "tool": chunk["tool_name"],
                        "result": tool_result
                    })
                    
                    # Update voice if mockingbird was activated/deactivated
                    current_voice_id = self.mockingbird.get_current_voice_id(session_id)
                    continue
                
                # Handle text tokens
                if isinstance(chunk, str):
                    full_response += chunk
                    sentence_buffer += chunk
                    
                    sentence, sentence_buffer = self._extract_complete_sentence(sentence_buffer)
                    
                    if sentence:
                        sentence_count += 1
                        cleaned = self._clean_llm_output(sentence)
                        cleaned = self._add_prosody_hints(cleaned)
                        
                        if not cleaned:
                            continue
                        
                        if sentence_count == 1:
                            first_sentence_time = (time.time() - start_time) * 1000
                            logger.info(f"⚡ First sentence in {first_sentence_time:.0f}ms")
                        
                        logger.info(f"🔊 Sentence #{sentence_count}: '{cleaned[:60]}...'")
                        await self._send_to_tts_natural(
                            room_name=room_name,
                            text=cleaned,
                            session_id=session_id,
                            voice_id=current_voice_id
                        )
                        self.total_sentences_sent += 1
            
            # Send remaining text
            if sentence_buffer.strip():
                cleaned = self._clean_llm_output(sentence_buffer.strip())
                cleaned = self._add_prosody_hints(cleaned)
                
                if cleaned and len(cleaned) >= self.min_chunk_size:
                    sentence_count += 1
                    logger.info(f"🔊 Final fragment: '{cleaned[:50]}...'")
                    await self._send_to_tts_natural(
                        room_name=room_name,
                        text=cleaned,
                        session_id=session_id,
                        voice_id=current_voice_id
                    )
                    self.total_sentences_sent += 1
            
            llm_time = (time.time() - llm_start) * 1000
            
            # Add to history
            if not is_partial:
                logger.info(f"💾 Adding to history...")
                self.history.add_message(session_id, "user", text)
                self.history.add_message(session_id, "assistant", full_response)
                logger.info(f"✅ History updated: now {len(self.history.get_history(session_id))} messages")
            
            total_time = (time.time() - start_time) * 1000
            
            logger.info("─" * 80)
            logger.info(f"✅ SUCCESS")
            logger.info(f"   Voice: {current_voice_id}")
            logger.info(f"   Tools used: {len(tool_calls_made)}")
            logger.info(f"   Total time: {total_time:.0f}ms")
            logger.info("=" * 80)
            
            return {
                "status": "success",
                "response": full_response,
                "sentences_sent": sentence_count,
                "tool_calls": tool_calls_made,
                "voice_id": current_voice_id,
                "total_time_ms": total_time
            }
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ Error: {e}", exc_info=True)
            logger.error("=" * 80)
            
            error_msg = "Sorry, I'm having trouble right now."
            try:
                await self._send_to_tts_natural(room_name, error_msg, session_id, "default")
            except:
                pass
            
            return {"status": "error", "error": str(e)}
    
    async def _stream_gemini_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        history: List[Dict],
        session_id: str
    ) -> AsyncIterator:
        """Stream from Gemini with tool calling support - NEW SDK"""
        try:
            # ✅ NEW SDK IMPORT
            from google import genai
            
            client = genai.Client(api_key=self.gemini_api_key)
            logger.debug("🌐 Connecting to Gemini API (new SDK)...")
            
            # Build full context
            if history:
                context_lines = [f"{msg['role']}: {msg['content']}" for msg in history]
                context = "\n".join(context_lines)
                prompt = f"{system_prompt}\n\n=== Recent Conversation ===\n{context}\n\n=== Current Message ===\nUser: {user_message}\n\nYour response:"
            else:
                prompt = f"{system_prompt}\n\nUser: {user_message}\n\nYour response:"
            
            # Configure with tools
            config = genai.types.GenerateContentConfig(
                temperature=0.9,
                max_output_tokens=500,
                top_p=0.95,
                top_k=50,
                tools=MOCKINGBIRD_TOOLS
            )
            
            # Stream with tool support
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=config
            ):
                # Check for tool calls
                if hasattr(chunk, 'function_calls') and chunk.function_calls:
                    for func_call in chunk.function_calls:
                        yield {
                            "type": "tool_call",
                            "tool_name": func_call.name,
                            "tool_args": dict(func_call.args) if func_call.args else {}
                        }
                
                # Yield text
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini error: {e}")
            logger.info("🔄 Falling back to gemini-2.0-flash...")
            
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_api_key)
                
                # Build prompt again
                if history:
                    context_lines = [f"{msg['role']}: {msg['content']}" for msg in history]
                    context = "\n".join(context_lines)
                    prompt = f"{system_prompt}\n\n=== Recent Conversation ===\n{context}\n\n=== Current Message ===\nUser: {user_message}\n\nYour response:"
                else:
                    prompt = f"{system_prompt}\n\nUser: {user_message}\n\nYour response:"
                
                config = genai.types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=500,
                    tools=MOCKINGBIRD_TOOLS
                )
                
                for chunk in client.models.generate_content_stream(
                    model='gemini-2.0-flash',
                    contents=prompt,
                    config=config
                ):
                    if hasattr(chunk, 'function_calls') and chunk.function_calls:
                        for func_call in chunk.function_calls:
                            yield {
                                "type": "tool_call",
                                "tool_name": func_call.name,
                                "tool_args": dict(func_call.args) if func_call.args else {}
                            }
                    
                    if chunk.text:
                        yield chunk.text
                        
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm having technical difficulties."
    
    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str,
        room_name: str
    ) -> Dict[str, Any]:
        """Execute a tool call"""
        logger.info(f"🔧 Executing tool: {tool_name}")
        
        try:
            if tool_name == "enable_mockingbird":
                result = await self.mockingbird.enable(session_id, session_id)
                self.mockingbird_activations += 1
                
                # Send instruction to user
                if result.get("message"):
                    await self._send_to_tts_natural(
                        room_name=room_name,
                        text=result["message"],
                        session_id=session_id,
                        voice_id="default"
                    )
                
                return result
            
            elif tool_name == "disable_mockingbird":
                result = await self.mockingbird.disable(session_id)
                
                # Confirm with user (in default voice)
                if result.get("message"):
                    await self._send_to_tts_natural(
                        room_name=room_name,
                        text=result["message"],
                        session_id=session_id,
                        voice_id="default"
                    )
                
                return result
            
            elif tool_name == "check_mockingbird_status":
                return self.mockingbird.get_status(session_id)
            
            else:
                return {"status": "unknown_tool", "tool": tool_name}
                
        except Exception as e:
            logger.error(f"❌ Tool execution error: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _send_to_tts_natural(
        self,
        room_name: str,
        text: str,
        session_id: str,
        voice_id: str = "default"
    ):
        """Send to TTS with natural pacing"""
        try:
            if session_id in self._last_tts_time:
                time_since_last = time.time() - self._last_tts_time[session_id]
                if time_since_last < self._natural_pause_duration:
                    delay = self._natural_pause_duration - time_since_last
                    await asyncio.sleep(delay)
            
            tts_start = time.time()
            self._last_tts_time[session_id] = tts_start
            
            await asyncio.wait_for(
                self.tts.publish_to_room(
                    room_name=room_name,
                    text=text,
                    voice_id=voice_id,
                    streaming=True
                ),
                timeout=45.0
            )
            
            tts_time = (time.time() - tts_start) * 1000
            logger.debug(f"   TTS completed in {tts_time:.0f}ms")
            
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")
    
    async def handle_interruption(self, session_id: str, room_name: str):
        """Handle user interruption"""
        logger.info(f"🛑 User interrupted session {session_id}")
        return {"status": "interrupted"}
    
    def get_stats(self) -> Dict:
        """Get statistics"""
        mockingbird_stats = self.mockingbird.get_stats()
        
        return {
            "mode": "natural_speech_with_mockingbird",
            "active_sessions": len(self.history.sessions),
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "mockingbird_activations": self.mockingbird_activations,
            "mockingbird": mockingbird_stats
        }
    
    def clear_session(self, session_id: str):
        """Clear session data"""
        self.history.clear_session(session_id)
        
        if session_id in self._recent_transcripts:
            del self._recent_transcripts[session_id]
        if session_id in self._last_tts_time:
            del self._last_tts_time[session_id]
        if session_id in self._processing_lock:
            del self._processing_lock[session_id]
    
    async def health_check(self) -> Dict:
        """Health check"""
        mockingbird_stats = self.mockingbird.get_stats()
        
        return {
            "healthy": True,
            "assistant": "natural_speech_with_mockingbird",
            "mockingbird": mockingbird_stats,
            "stats": self.get_stats()
        }
