"""
Simple Voice Assistant - Natural Conversation (FULLY FIXED + OPTIMIZED)
All fixes applied: Output cleaning, better timeout, improved interruption handling,
smart sentence splitting, and enhanced performance

KEY IMPROVEMENTS:
1. ✅ Removes "June:" prefix from output
2. ✅ Better story-telling capability
3. ✅ Natural explanations like ChatGPT/Claude
4. ✅ Voice-optimized pacing
5. ✅ Proper history management with debug logging
6. ✅ 30s TTS timeout (increased from 15s)
7. ✅ Better interruption handling
8. ✅ Smart sentence splitting at 120 chars for faster response
9. ✅ Early break at commas/semicolons for natural pacing
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
    
    def __init__(self, max_turns: int = 5):
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
    NOW WITH ALL FIXES + OPTIMIZATIONS APPLIED
    """
    
    def __init__(self, gemini_api_key: str, tts_service):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=5)
        
        # Simple sentence detection
        self.sentence_end = re.compile(r'[.!?。！？]+\s*')
        
        # ✅ NEW: Smart splitting configuration
        self.max_sentence_chars = 120  # Target: ~8-10s of speech
        self.early_split_chars = 100    # Start looking for breaks at this length
        self.split_opportunities = re.compile(r'[,;:—]\s+')  # Good places to split
        
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
        logger.info("✅ Simple Voice Assistant (FULLY OPTIMIZED) initialized")
        logger.info("   - Mode: Direct, action-oriented responses")
        logger.info("   - History: Last 5 exchanges")
        logger.info("   - Output cleaning: Removes speaker labels")
        logger.info("   - TTS timeout: 30 seconds")
        logger.info("   - Smart sentence splitting: Max 120 chars")
        logger.info("   - Early breaks at commas/semicolons")
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
    
    def _clean_llm_output(self, text: str) -> str:
        """Remove any speaker labels that snuck into the output"""
        # Remove "June:" or "June :" at the start
        text = re.sub(r'^(June\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        
        # Remove "Assistant:" or similar
        text = re.sub(r'^(Assistant\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        
        return text.strip()
    
    def _smart_sentence_split(self, text_buffer: str) -> tuple[str, str]:
        """
        Split long sentences early at natural break points
        
        Returns:
            (sentence_to_send, remaining_buffer)
        """
        # If under target length, don't split
        if len(text_buffer) < self.early_split_chars:
            return "", text_buffer
        
        # If we hit max length, force split at next opportunity
        if len(text_buffer) >= self.max_sentence_chars:
            # Look for comma, semicolon, colon, etc.
            matches = list(self.split_opportunities.finditer(text_buffer))
            if matches:
                # Find the split closest to max_sentence_chars
                best_match = None
                best_distance = float('inf')
                
                for match in matches:
                    distance = abs(match.end() - self.max_sentence_chars)
                    if distance < best_distance:
                        best_distance = distance
                        best_match = match
                
                if best_match and best_match.end() > 50:  # Don't split too early
                    split_pos = best_match.end()
                    sentence = text_buffer[:split_pos].strip()
                    remaining = text_buffer[split_pos:].strip()
                    logger.debug(f"📏 Early split at {split_pos} chars: '{sentence[:30]}...'")
                    return sentence, remaining
        
        # No good split point found
        return "", text_buffer
    
    def _build_prompt(self, user_message: str, history: List[Dict]) -> str:
        """Build improved prompt WITHOUT speaker labels in output"""
        
        # Improved system prompt - explicitly tell it NOT to use labels
        system = """You are June, a knowledgeable and friendly voice assistant.

CRITICAL OUTPUT RULE:
• Do NOT include "June:" or any speaker labels in your responses
• Start speaking directly - your words will be converted to speech
• Never write "June: " before your response

CORE BEHAVIOR:
• Give direct, helpful responses - don't ask if you should help, just help
• For requests (stories, explanations, etc.), fulfill them immediately
• Be concise but complete - aim for 2-4 sentences unless more detail is needed
• Speak naturally, like a helpful friend who knows a lot

WHEN ASKED TO CREATE CONTENT (stories, poems, etc.):
• Start creating immediately - no preamble
• Jump right into the content
• Keep it concise for voice (30-60 seconds of speech)

WHEN ASKED TO EXPLAIN (science, history, tech):
• Give clear, accurate explanations
• Use analogies and examples when helpful
• Break complex topics into understandable pieces
• Be thorough but voice-friendly (not too long)

EXAMPLES:

❌ BAD (with label):
User: "Tell me a story about Pokemon"
You: "June: In a small village..."

✅ GOOD (direct speech):
User: "Tell me a story about Pokemon"
You: "In a small village near Mount Silver, a young trainer discovered a mysterious Pokeball..."

❌ BAD (with meta-talk):
User: "Explain dark matter"
You: "Sure! Let me explain that for you. Dark matter is..."

✅ GOOD (direct):
User: "Explain dark matter"
You: "Dark matter is invisible material that makes up about 85% of the universe's mass..."

Remember: Speak naturally and directly. No labels, no preamble."""

        # Format conversation history
        if history:
            context_lines = []
            for msg in history:
                # Show role clearly in context but not in output
                role = "User" if msg['role'] == 'user' else "June (you said)"
                content = msg['content']
                context_lines.append(f"{role}: {content}")
            
            context = "\n".join(context_lines)
            
            prompt = f"""{system}

=== Recent Conversation ===
{context}

=== Current User Message ===
User: {user_message}

Your response (speak directly, no "June:" label):"""
        else:
            # No history - fresh conversation
            prompt = f"""{system}

User: {user_message}

Your response (speak directly, no "June:" label):"""
        
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
        
        # Better interruption handling
        word_count = len(text.strip().split())
        
        if lock.locked():
            # If it's a short input while processing, skip it
            if word_count < 5:
                logger.warning(f"⚠️ Already processing, skipping short input: '{text}'")
                return {
                    "status": "skipped",
                    "reason": "already_processing",
                    "text": text[:100]
                }
            else:
                # If it's a longer input, this might be an intentional interruption
                logger.info(f"🛑 User interrupting with new request: '{text[:50]}...'")
                logger.info(f"   (Previous response will complete, but new request will be queued)")
                # Let it wait for the lock - will process after current response finishes
        
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
            
            # Stream LLM response with SMART CHUNKING
            full_response = ""
            sentence_buffer = ""
            sentence_count = 0
            first_sentence_time = None
            
            logger.info(f"🧠 Starting LLM stream...")
            llm_start = time.time()
            
            async for token in self._stream_gemini(prompt):
                full_response += token
                sentence_buffer += token
                
                # ✅ NEW: Check for early split opportunity
                early_sentence, sentence_buffer = self._smart_sentence_split(sentence_buffer)
                
                if early_sentence:
                    # We found a good early split point
                    sentence_count += 1
                    cleaned_sentence = self._clean_llm_output(early_sentence)
                    
                    if cleaned_sentence:
                        # Track first sentence timing
                        if sentence_count == 1:
                            first_sentence_time = (time.time() - start_time) * 1000
                            logger.info(f"⚡ First sentence in {first_sentence_time:.0f}ms: '{cleaned_sentence[:40]}...'")
                            
                            # Update running average
                            if self.avg_first_sentence_ms == 0:
                                self.avg_first_sentence_ms = first_sentence_time
                            else:
                                self.avg_first_sentence_ms = (
                                    self.avg_first_sentence_ms * 0.9 + first_sentence_time * 0.1
                                )
                        
                        logger.info(f"🔊 Sentence #{sentence_count} (early split): '{cleaned_sentence[:50]}...'")
                        await self._send_to_tts(room_name, cleaned_sentence, session_id)
                        self.total_sentences_sent += 1
                
                # Check for natural sentence end
                match = self.sentence_end.search(sentence_buffer)
                if match:
                    sentence = sentence_buffer[:match.end()].strip()
                    sentence_buffer = sentence_buffer[match.end():]
                    
                    if sentence:
                        sentence_count += 1
                        cleaned_sentence = self._clean_llm_output(sentence)
                        
                        if not cleaned_sentence:
                            continue
                        
                        # Track first sentence timing
                        if sentence_count == 1:
                            first_sentence_time = (time.time() - start_time) * 1000
                            logger.info(f"⚡ First sentence in {first_sentence_time:.0f}ms: '{cleaned_sentence[:40]}...'")
                            
                            # Update running average
                            if self.avg_first_sentence_ms == 0:
                                self.avg_first_sentence_ms = first_sentence_time
                            else:
                                self.avg_first_sentence_ms = (
                                    self.avg_first_sentence_ms * 0.9 + first_sentence_time * 0.1
                                )
                        
                        # Send cleaned sentence to TTS
                        logger.info(f"🔊 Sentence #{sentence_count}: '{cleaned_sentence[:50]}...'")
                        await self._send_to_tts(room_name, cleaned_sentence, session_id)
                        self.total_sentences_sent += 1
            
            # Send any remaining text (cleaned)
            if sentence_buffer.strip():
                cleaned_fragment = self._clean_llm_output(sentence_buffer.strip())
                if cleaned_fragment:
                    sentence_count += 1
                    logger.info(f"🔊 Final fragment: '{cleaned_fragment[:50]}...'")
                    await self._send_to_tts(room_name, cleaned_fragment, session_id)
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
        """Send text to TTS service with natural pacing and increased timeout"""
        try:
            # Natural pacing between sentences
            if session_id in self._last_tts_time:
                time_since_last = time.time() - self._last_tts_time[session_id]
                if time_since_last < 0.4:
                    delay = 0.4 - time_since_last
                    logger.debug(f"⏸️ Pacing delay: {delay:.1f}s")
                    await asyncio.sleep(delay)
            
            tts_start = time.time()
            self._last_tts_time[session_id] = tts_start
            
            # ✅ FIXED: Increased timeout from 15s to 30s
            try:
                await asyncio.wait_for(
                    self.tts.publish_to_room(
                        room_name=room_name,
                        text=text,
                        voice_id="default",
                        streaming=True
                    ),
                    timeout=30.0  # ← Increased from 15.0
                )
            except asyncio.TimeoutError:
                logger.error(f"❌ TTS timeout (>30s) for: '{text[:50]}...'")
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
            "mode": "simple_voice_assistant_fully_optimized",
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "avg_first_sentence_ms": round(self.avg_first_sentence_ms, 1),
            "ignore_partials": self.ignore_partials,
            "duplicate_window_seconds": self._duplicate_window,
            "max_sentence_chars": self.max_sentence_chars,
            "early_split_chars": self.early_split_chars,
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
            "assistant": "simple_voice_assistant_fully_optimized",
            "tts_available": self.tts is not None,
            "gemini_configured": bool(self.gemini_api_key),
            "stats": self.get_stats()
        }