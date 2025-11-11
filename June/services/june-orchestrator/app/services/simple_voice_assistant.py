"""
Simple Voice Assistant - Natural Conversation (IMPROVED)
Fixes: Better prompting for direct responses and story-telling

KEY IMPROVEMENTS:
1. ✅ More direct, action-oriented responses
2. ✅ Better story-telling capability
3. ✅ Natural explanations like ChatGPT/Claude
4. ✅ Voice-optimized pacing
5. ✅ Proper history management with debug logging
"""
import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, AsyncIterator
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Single conversation message"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime


class ConversationHistory:
    """Simple in-memory conversation history with better logging"""
    
    def __init__(self, max_turns: int = 5):  # Increased from 3 to 5
        self.sessions: Dict[str, List[Message]] = {}
        self.max_turns = max_turns
        logger.info(f"✅ ConversationHistory initialized (max_turns={max_turns})")
    
    def add_message(self, session_id: str, role: str, content: str):
        """Add message and auto-trim old history"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
            logger.info(f"🆕 Created new conversation for session {session_id[:8]}...")
        
        self.sessions[session_id].append(
            Message(role=role, content=content, timestamp=datetime.utcnow())
        )
        
        # Keep only last N exchanges (user+assistant pairs)
        max_messages = self.max_turns * 2
        before_count = len(self.sessions[session_id])
        
        if before_count > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]
            logger.info(f"🗑️ Trimmed history for {session_id[:8]}...: {before_count} → {len(self.sessions[session_id])} messages")
        
        # Log current state
        logger.debug(f"📚 History for {session_id[:8]}... now has {len(self.sessions[session_id])} messages")
    
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history as dict list for LLM"""
        if session_id not in self.sessions:
            logger.debug(f"📭 No history found for {session_id[:8]}...")
            return []
        
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
        
        logger.debug(f"📚 Retrieved {len(history)} messages for {session_id[:8]}...")
        return history
    
    def clear_session(self, session_id: str):
        """Clear history for a session"""
        if session_id in self.sessions:
            msg_count = len(self.sessions[session_id])
            del self.sessions[session_id]
            logger.info(f"🗑️ Cleared {msg_count} messages for session {session_id[:8]}...")


class SimpleVoiceAssistant:
    """
    Voice assistant with natural explanations and better story-telling
    """
    
    def __init__(self, gemini_api_key: str, tts_service):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=5)  # Keep more context
        
        # Simple sentence detection
        self.sentence_end = re.compile(r'[.!?。！？]+\s*')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0
        self.avg_first_sentence_ms = 0
        
        # TTS pacing tracker
        self._last_tts_time: Dict[str, float] = {}
        
        # Deduplication
        self._recent_transcripts: Dict[str, tuple[str, float]] = {}
        self._duplicate_window = 3.0
        
        # Processing locks per session
        self._processing_lock: Dict[str, asyncio.Lock] = {}
        
        # Configuration
        self.ignore_partials = True
        
        logger.info("=" * 80)
        logger.info("✅ Simple Voice Assistant (IMPROVED) initialized")
        logger.info("   - Mode: Direct, action-oriented responses")
        logger.info("   - History: Last 5 exchanges")
        logger.info("   - Better story-telling")
        logger.info("   - Natural explanations")
        logger.info("=" * 80)
    
    def _is_duplicate_transcript(self, session_id: str, text: str) -> bool:
        """Check if this transcript is a duplicate of a recent one"""
        current_time = time.time()
        
        # Clean up old entries
        expired = [
            sid for sid, (_, ts) in self._recent_transcripts.items()
            if current_time - ts > self._duplicate_window
        ]
        for sid in expired:
            del self._recent_transcripts[sid]
        
        # Check for duplicate
        if session_id in self._recent_transcripts:
            recent_text, recent_time = self._recent_transcripts[session_id]
            if recent_text == text and current_time - recent_time < self._duplicate_window:
                logger.warning(f"⚠️ Duplicate detected: '{text[:30]}...' (within {current_time - recent_time:.1f}s)")
                return True
        
        # Update tracker
        self._recent_transcripts[session_id] = (text, current_time)
        return False
    
    def _build_prompt(self, user_message: str, history: List[Dict]) -> str:
        """Build improved prompt for direct, helpful responses"""
        
        # Improved system prompt - more direct, less meta-commentary
        system = """You are June, a knowledgeable and friendly voice assistant.

CORE BEHAVIOR:
• Give direct, helpful responses - don't ask if you should help, just help
• For requests (stories, explanations, etc.), fulfill them immediately
• Be concise but complete - aim for 2-4 sentences unless more detail is needed
• Speak naturally, like a helpful friend who knows a lot

WHEN ASKED TO CREATE CONTENT (stories, poems, etc.):
• Start creating immediately - no "I'll write that for you" preamble
• Jump right into the content
• Keep it concise for voice (30-60 seconds of speech)

WHEN ASKED TO EXPLAIN (science, history, tech):
• Give clear, accurate explanations
• Use analogies and examples when helpful
• Break complex topics into understandable pieces
• Be thorough but voice-friendly (not too long)

CONVERSATION STYLE:
• Natural and warm, not robotic
• No meta-commentary about what you're doing
• Just do it

EXAMPLES:

❌ BAD (too much meta-talk):
User: "Tell me a story about Pokemon"
You: "Sure! I can write that for you. Let me create something now..."

✅ GOOD (direct):
User: "Tell me a story about Pokemon"  
You: "In a small village near Mount Silver, a young trainer named Kai discovered a mysterious Pokeball glowing in the forest..."

❌ BAD (asking unnecessary questions):
User: "Explain dark matter"
You: "Would you like a simple explanation or detailed one?"

✅ GOOD (just explain):
User: "Explain dark matter"
You: "Dark matter is invisible material that makes up about 85% of the universe's mass. We can't see it directly, but we know it's there because we can see its gravitational effects on galaxies and light..."

Remember: You're helpful and direct. When someone asks for something, just do it naturally."""

        # Format conversation history
        if history:
            context_lines = []
            for msg in history:
                role = "User" if msg['role'] == 'user' else "June"
                content = msg['content']
                context_lines.append(f"{role}: {content}")
            
            context = "\n".join(context_lines)
            
            prompt = f"""{system}

=== Recent Conversation ===
{context}

=== Current User Message ===
User: {user_message}

June:"""
        else:
            # No history - fresh conversation
            prompt = f"""{system}

User: {user_message}

June:"""
        
        return prompt
    
    async def handle_transcript(
        self,
        session_id: str,
        room_name: str,
        text: str,
        is_partial: bool = False
    ) -> Dict:
        """Main entry point for STT transcripts"""
        start_time = time.time()
        self.total_requests += 1
        
        # Ignore all partials
        if is_partial and self.ignore_partials:
            logger.debug(f"⏸️ Ignoring partial: '{text[:50]}...'")
            return {
                "status": "skipped",
                "reason": "partial_ignored",
                "text": text[:100]
            }
        
        # Check for duplicates
        if self._is_duplicate_transcript(session_id, text):
            return {
                "status": "skipped",
                "reason": "duplicate_transcript",
                "text": text[:100]
            }
        
        # Get or create processing lock
        if session_id not in self._processing_lock:
            self._processing_lock[session_id] = asyncio.Lock()
        
        lock = self._processing_lock[session_id]
        
        # Check if already processing
        if lock.locked():
            logger.warning(f"⚠️ Already processing for session {session_id[:8]}..., skipping")
            return {
                "status": "skipped",
                "reason": "already_processing",
                "text": text[:100]
            }
        
        # Process with lock
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
        """Internal method to process transcript (called within lock)"""
        
        # Skip tiny inputs
        word_count = len(text.strip().split())
        char_count = len(text.strip())
        
        if word_count < 2:
            logger.debug(f"⏸️ Text too short: '{text}' ({word_count} words)")
            return {
                "status": "skipped",
                "reason": "too_short",
                "word_count": word_count
            }
        
        # Log what we're processing
        status = "PARTIAL" if is_partial else "FINAL"
        logger.info("=" * 80)
        logger.info(f"📥 [{status}] Session: {session_id[:8]}")
        logger.info(f"📝 Text: '{text}'")
        logger.info(f"📊 Words: {word_count}, Chars: {char_count}")
        
        try:
            # Get conversation history with debug logging
            history = self.history.get_history(session_id)
            logger.info(f"📚 History: {len(history)} messages")
            
            if history:
                logger.debug("📜 Current conversation context:")
                for i, msg in enumerate(history[-4:]):  # Show last 2 exchanges
                    logger.debug(f"   {i+1}. {msg['role']}: {msg['content'][:60]}...")
            
            # Build prompt with improved system instructions
            prompt = self._build_prompt(text, history)
            logger.debug(f"🔧 Prompt length: {len(prompt)} chars")
            
            # Stream LLM response with sentence chunking
            full_response = ""
            sentence_buffer = ""
            sentence_count = 0
            first_sentence_time = None
            
            logger.info(f"🧠 Starting LLM stream...")
            llm_start = time.time()
            
            async for token in self._stream_gemini(prompt):
                full_response += token
                sentence_buffer += token
                
                # Check if we have a complete sentence
                match = self.sentence_end.search(sentence_buffer)
                if match:
                    sentence = sentence_buffer[:match.end()].strip()
                    sentence_buffer = sentence_buffer[match.end():]
                    
                    if sentence:
                        sentence_count += 1
                        
                        # Track first sentence timing
                        if sentence_count == 1:
                            first_sentence_time = (time.time() - start_time) * 1000
                            logger.info(f"⚡ First sentence in {first_sentence_time:.0f}ms: '{sentence[:40]}...'")
                            
                            # Update running average
                            if self.avg_first_sentence_ms == 0:
                                self.avg_first_sentence_ms = first_sentence_time
                            else:
                                self.avg_first_sentence_ms = (
                                    self.avg_first_sentence_ms * 0.9 + first_sentence_time * 0.1
                                )
                        
                        # Send to TTS sequentially
                        logger.info(f"🔊 Sentence #{sentence_count}: '{sentence[:50]}...'")
                        await self._send_to_tts(room_name, sentence, session_id)
                        self.total_sentences_sent += 1
            
            # Send any remaining text
            if sentence_buffer.strip():
                sentence_count += 1
                logger.info(f"🔊 Final fragment: '{sentence_buffer[:50]}...'")
                await self._send_to_tts(room_name, sentence_buffer.strip(), session_id)
                self.total_sentences_sent += 1
            
            llm_time = (time.time() - llm_start) * 1000
            
            # Add to history (ONLY for finals) - WITH DEBUG LOGGING
            if not is_partial:
                logger.info(f"💾 Adding to history...")
                logger.debug(f"   User message: '{text}'")
                logger.debug(f"   Assistant response: '{full_response[:100]}...'")
                
                self.history.add_message(session_id, "user", text)
                self.history.add_message(session_id, "assistant", full_response)
                
                new_history = self.history.get_history(session_id)
                logger.info(f"✅ History updated: now {len(new_history)} messages total")
            else:
                logger.info(f"⏭️ Partial - not adding to history")
            
            total_time = (time.time() - start_time) * 1000
            
            logger.info("─" * 80)
            logger.info(f"✅ SUCCESS:")
            logger.info(f"   Response: {len(full_response)} chars")
            logger.info(f"   Sentences: {sentence_count}")
            logger.info(f"   LLM time: {llm_time:.0f}ms")
            logger.info(f"   First sentence: {first_sentence_time:.0f}ms" if first_sentence_time else "   First sentence: N/A")
            logger.info(f"   Total time: {total_time:.0f}ms")
            logger.info("=" * 80)
            
            return {
                "status": "success",
                "response": full_response,
                "sentences_sent": sentence_count,
                "total_time_ms": total_time,
                "llm_time_ms": llm_time,
                "first_sentence_ms": first_sentence_time,
                "was_partial": is_partial,
                "history_size": len(self.history.get_history(session_id))
            }
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ ERROR processing transcript: {e}", exc_info=True)
            logger.error("=" * 80)
            
            # Send error message to user
            error_msg = "Sorry, I'm having trouble right now. Can you repeat that?"
            try:
                await self._send_to_tts(room_name, error_msg, session_id)
            except:
                pass
            
            return {
                "status": "error",
                "error": str(e),
                "total_time_ms": (time.time() - start_time) * 1000
            }
    
    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        """Stream tokens from Gemini"""
        try:
            from google import genai
            
            client = genai.Client(api_key=self.gemini_api_key)
            logger.debug("🌐 Connecting to Gemini API...")
            
            # Stream with optimized settings for voice
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.8,  # Slightly more creative for stories
                    max_output_tokens=400,  # More tokens for explanations/stories
                    top_p=0.95,
                    top_k=40,
                ),
            ):
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini streaming error: {e}")
            logger.info("🔄 Falling back to gemini-2.0-flash...")
            
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_api_key)
                
                for chunk in client.models.generate_content_stream(
                    model='gemini-2.0-flash',
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.8,
                        max_output_tokens=400
                    ),
                ):
                    if chunk.text:
                        yield chunk.text
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties."
    
    async def _send_to_tts(self, room_name: str, text: str, session_id: str):
        """Send text to TTS service with natural pacing and timeout"""
        try:
            # Natural pacing between sentences
            if session_id in self._last_tts_time:
                time_since_last = time.time() - self._last_tts_time[session_id]
                if time_since_last < 0.4:  # Reduced from 1.5s - faster pacing
                    delay = 0.4 - time_since_last
                    logger.debug(f"⏸️ Pacing delay: {delay:.1f}s")
                    await asyncio.sleep(delay)
            
            tts_start = time.time()
            self._last_tts_time[session_id] = tts_start
            
            # Send with timeout
            try:
                await asyncio.wait_for(
                    self.tts.publish_to_room(
                        room_name=room_name,
                        text=text,
                        voice_id="default",
                        streaming=True
                    ),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.error(f"❌ TTS timeout (>10s) for: '{text[:50]}...'")
                return
            
            tts_time = (time.time() - tts_start) * 1000
            logger.debug(f"   TTS completed in {tts_time:.0f}ms")
            
        except Exception as e:
            logger.error(f"❌ TTS error for session {session_id}: {e}")
    
    async def handle_interruption(self, session_id: str, room_name: str):
        """Handle user interruption"""
        logger.info(f"🛑 User interrupted session {session_id}")
        
        return {
            "status": "interrupted",
            "session_id": session_id,
            "message": "Interruption handled naturally by streaming"
        }
    
    def get_stats(self) -> Dict:
        """Get simple statistics"""
        active_sessions = len(self.history.sessions)
        total_messages = sum(len(msgs) for msgs in self.history.sessions.values())
        
        # Detailed session info
        session_details = {}
        for session_id, msgs in self.history.sessions.items():
            session_details[session_id[:8]] = {
                "messages": len(msgs),
                "last_activity": msgs[-1].timestamp.isoformat() if msgs else None
            }
        
        return {
            "mode": "simple_voice_assistant_improved",
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "avg_first_sentence_ms": round(self.avg_first_sentence_ms, 1),
            "ignore_partials": self.ignore_partials,
            "duplicate_window_seconds": self._duplicate_window,
            "sessions": session_details
        }
    
    def clear_session(self, session_id: str):
        """Clear conversation history for a session"""
        self.history.clear_session(session_id)
        
        # Clean up tracking data
        if session_id in self._recent_transcripts:
            del self._recent_transcripts[session_id]
        if session_id in self._last_tts_time:
            del self._last_tts_time[session_id]
        if session_id in self._processing_lock:
            del self._processing_lock[session_id]
    
    async def health_check(self) -> Dict:
        """Health check endpoint"""
        return {
            "healthy": True,
            "assistant": "simple_voice_assistant_improved",
            "tts_available": self.tts is not None,
            "gemini_configured": bool(self.gemini_api_key),
            "stats": self.get_stats()
        }