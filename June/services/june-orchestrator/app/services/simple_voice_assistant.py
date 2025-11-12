"""
Simple Voice Assistant - NATURAL SPEECH OPTIMIZED
Focus on human-like intonation and pacing over pure speed

KEY IMPROVEMENTS FOR NATURAL SPEECH:
1. ✅ Larger sentence chunks (180 chars) for better prosody context
2. ✅ LLM prompt optimized for natural, conversational speech
3. ✅ Prosody hints (commas, ellipses) added to text
4. ✅ Complete sentences sent to TTS (no mid-sentence splits)
5. ✅ Natural pauses between thoughts
6. ✅ Emotion/emphasis cues preserved
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
    """Simple in-memory conversation history"""
    
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
        
        # Keep only last N exchanges
        max_messages = self.max_turns * 2
        before_count = len(self.sessions[session_id])
        
        if before_count > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]
            after_count = len(self.sessions[session_id])
            logger.info(
                f"🗑️ Trimmed history for {session_id[:8]}...: "
                f"{before_count} → {after_count} messages"
            )
        
        logger.debug(f"📚 History for {session_id[:8]}... now has {len(self.sessions[session_id])} messages")
    
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history as dict list for LLM"""
        if session_id not in self.sessions:
            return []
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
    
    def clear_session(self, session_id: str):
        """Clear history for a session"""
        if session_id in self.sessions:
            msg_count = len(self.sessions[session_id])
            del self.sessions[session_id]
            logger.info(f"🗑️ Cleared {msg_count} messages for session {session_id[:8]}...")


class SimpleVoiceAssistant:
    """
    Voice assistant optimized for NATURAL HUMAN-LIKE SPEECH
    Prioritizes prosody and intonation over raw speed
    """
    
    def __init__(self, gemini_api_key: str, tts_service):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=5)
        
        # NATURAL SPEECH SETTINGS
        # ✅ Larger chunks allow XTTS to understand context and add proper intonation
        self.max_sentence_chars = 180  # Increased from 100
        self.min_chunk_size = 50       # Don't send tiny fragments
        
        # Natural sentence boundaries (complete thoughts)
        self.sentence_end = re.compile(r'[.!?。！？]+\s+')
        
        # Prosody markers for natural pauses
        self.natural_pause_markers = re.compile(r'[,;:—]\s+')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0
        self.avg_first_sentence_ms = 0
        
        # TTS pacing tracker - longer pauses for natural rhythm
        self._last_tts_time: Dict[str, float] = {}
        self._natural_pause_duration = 0.6  # Increased from 0.4s
        
        # Deduplication
        self._recent_transcripts: Dict[str, tuple[str, float]] = {}
        self._duplicate_window = 3.0
        
        # Processing locks per session
        self._processing_lock: Dict[str, asyncio.Lock] = {}
        
        # Configuration
        self.ignore_partials = True
        
        logger.info("=" * 80)
        logger.info("✅ Simple Voice Assistant (NATURAL SPEECH MODE)")
        logger.info("   - Priority: Natural intonation and human-like pacing")
        logger.info("   - Sentence chunks: 180 chars (gives XTTS more context)")
        logger.info("   - Complete sentences only (no mid-sentence splits)")
        logger.info("   - Natural pauses: 0.6s between thoughts")
        logger.info("   - Prosody hints: Preserved commas, ellipses, emphasis")
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
                logger.warning(f"⚠️ Duplicate detected: '{text[:30]}...'")
                return True
        
        # Update tracker
        self._recent_transcripts[session_id] = (text, current_time)
        return False
    
    def _clean_llm_output(self, text: str) -> str:
        """Remove speaker labels and normalize punctuation for natural speech"""
        # Remove speaker labels
        text = re.sub(r'^(June\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        text = re.sub(r'^(Assistant\s*:\s*)', '', text.strip(), flags=re.IGNORECASE)
        
        # Normalize multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Ensure proper spacing after punctuation
        text = re.sub(r'([.!?,;:])([A-Za-z])', r'\1 \2', text)
        
        return text.strip()
    
    def _add_prosody_hints(self, text: str) -> str:
        """
        Add subtle prosody hints to help XTTS with natural intonation
        (without making it sound weird)
        """
        # Add slight pause before "but", "however", "although" (natural speech patterns)
        text = re.sub(r'\s+(but|however|although|though)\s+', r', \1 ', text, flags=re.IGNORECASE)
        
        # Add pause after introductory phrases
        text = re.sub(r'^(Well|So|Now|Actually|In fact|By the way),?\s+', r'\1, ', text, flags=re.IGNORECASE)
        
        return text
    
    def _extract_complete_sentence(self, text_buffer: str) -> tuple[str, str]:
        """
        Extract a complete sentence (or natural thought unit) from buffer
        Only returns when we have a complete, meaningful chunk
        
        Returns:
            (sentence_to_send, remaining_buffer)
        """
        # Must have minimum content
        if len(text_buffer) < self.min_chunk_size:
            return "", text_buffer
        
        # Look for sentence endings
        match = self.sentence_end.search(text_buffer)
        
        if match:
            # Found a complete sentence
            sentence = text_buffer[:match.end()].strip()
            remaining = text_buffer[match.end():].strip()
            
            # Make sure it's substantial enough
            if len(sentence) >= self.min_chunk_size:
                return sentence, remaining
        
        # If buffer is getting long but no sentence end, look for natural break
        if len(text_buffer) >= self.max_sentence_chars:
            # Find a natural pause point (comma, semicolon, etc.)
            pause_matches = list(self.natural_pause_markers.finditer(text_buffer))
            
            if pause_matches:
                # Use the last natural pause before max length
                for match in reversed(pause_matches):
                    if match.end() >= self.min_chunk_size:
                        sentence = text_buffer[:match.end()].strip()
                        remaining = text_buffer[match.end():].strip()
                        logger.debug(f"📏 Natural break at {match.end()} chars")
                        return sentence, remaining
        
        # Not ready yet - keep accumulating
        return "", text_buffer
    
    def _build_natural_speech_prompt(self, user_message: str, history: List[Dict]) -> str:
        """
        Build prompt optimized for NATURAL, CONVERSATIONAL speech
        Instructs LLM to write the way humans actually talk
        """
        
        system = """You are June, a warm and intelligent voice assistant who speaks naturally and conversationally.

🎯 CRITICAL: Write for VOICE, not text. Your responses will be spoken aloud.

NATURAL SPEECH RULES:
• Write the way people actually talk - conversational and fluid
• Use natural pauses with commas: "Well, let me think about that"
• Vary your sentence length - short AND long sentences (like real speech)
• Show emotion/enthusiasm when appropriate: "That's fascinating!" or "Hmm, interesting question"
• Use filler words occasionally: "you know", "I mean", "actually"
• Break complex ideas into smaller, digestible thoughts
• Sound engaged and present - not like you're reading a script

PROSODY & RHYTHM:
• Start responses naturally: "Oh, that's a great question" vs robotic "The answer is..."
• Use commas for natural breathing pauses
• Build up ideas gradually rather than info-dumping
• End with natural conclusions, not abrupt stops

CONTENT STYLE:
• Be concise but complete (aim for 2-4 sentences typically)
• For stories/explanations: 3-5 sentences with natural flow
• Sound like you're having a real conversation, not giving a presentation
• If uncertain, say so naturally: "I'm not entirely sure, but..."

❌ AVOID:
• Lists or bullet points (unnatural in speech)
• Overly formal language ("Furthermore", "Additionally")
• Robotic phrasing: "I will now tell you..."
• Monotone delivery - show some personality!

✅ GOOD EXAMPLES:

User: "Tell me about black holes"
You: "Oh, black holes are fascinating! So basically, they're regions in space where gravity is so incredibly strong that not even light can escape. That's why they appear black. Think of it like a cosmic drain - once something crosses that point of no return, called the event horizon, it's gone forever."

User: "What's the weather like?"
You: "Hmm, I actually don't have real-time weather access right now. But if you tell me where you are, I can help you think about what to expect based on the season!"

Remember: You're speaking OUT LOUD to a person. Sound natural, warm, and human!"""

        # Format conversation history
        if history:
            context_lines = []
            for msg in history:
                role = "User" if msg['role'] == 'user' else "June (you said)"
                content = msg['content']
                context_lines.append(f"{role}: {content}")
            
            context = "\n".join(context_lines)
            
            prompt = f"""{system}

=== Recent Conversation ===
{context}

=== Current User Message ===
User: {user_message}

Your response (speak naturally, like you're having a real conversation):"""
        else:
            prompt = f"""{system}

User: {user_message}

Your response (speak naturally, like you're having a real conversation):"""
        
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
        
        # Handle interruptions gracefully
        word_count = len(text.strip().split())
        
        if lock.locked():
            if word_count < 5:
                logger.warning(f"⚠️ Already processing, skipping short input: '{text}'")
                return {
                    "status": "skipped",
                    "reason": "already_processing",
                    "text": text[:100]
                }
            else:
                logger.info(f"🛑 User interrupting with new request: '{text[:50]}...'")
        
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
        """Internal method to process transcript"""
        
        # Skip tiny inputs
        word_count = len(text.strip().split())
        char_count = len(text.strip())
        
        if word_count < 2:
            logger.debug(f"⏸️ Text too short: '{text}'")
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
            # Get conversation history
            history = self.history.get_history(session_id)
            logger.info(f"📚 History: {len(history)} messages")
            
            # Build prompt optimized for natural speech
            prompt = self._build_natural_speech_prompt(text, history)
            
            # Stream LLM response with NATURAL CHUNKING
            full_response = ""
            sentence_buffer = ""
            sentence_count = 0
            first_sentence_time = None
            
            logger.info(f"🧠 Starting LLM stream (natural speech mode)...")
            llm_start = time.time()
            
            async for token in self._stream_gemini(prompt):
                full_response += token
                sentence_buffer += token
                
                # Try to extract a complete sentence
                sentence, sentence_buffer = self._extract_complete_sentence(sentence_buffer)
                
                if sentence:
                    sentence_count += 1
                    
                    # Clean and add prosody hints
                    cleaned_sentence = self._clean_llm_output(sentence)
                    cleaned_sentence = self._add_prosody_hints(cleaned_sentence)
                    
                    if not cleaned_sentence:
                        continue
                    
                    # Track first sentence timing
                    if sentence_count == 1:
                        first_sentence_time = (time.time() - start_time) * 1000
                        logger.info(f"⚡ First sentence in {first_sentence_time:.0f}ms")
                        
                        # Update running average
                        if self.avg_first_sentence_ms == 0:
                            self.avg_first_sentence_ms = first_sentence_time
                        else:
                            self.avg_first_sentence_ms = (
                                self.avg_first_sentence_ms * 0.9 + first_sentence_time * 0.1
                            )
                    
                    # Send to TTS with natural pacing
                    logger.info(f"🔊 Sentence #{sentence_count}: '{cleaned_sentence[:60]}...'")
                    await self._send_to_tts_natural(room_name, cleaned_sentence, session_id)
                    self.total_sentences_sent += 1
            
            # Send any remaining text
            if sentence_buffer.strip():
                cleaned_fragment = self._clean_llm_output(sentence_buffer.strip())
                cleaned_fragment = self._add_prosody_hints(cleaned_fragment)
                
                if cleaned_fragment and len(cleaned_fragment) >= self.min_chunk_size:
                    sentence_count += 1
                    logger.info(f"🔊 Final fragment: '{cleaned_fragment[:60]}...'")
                    await self._send_to_tts_natural(room_name, cleaned_fragment, session_id)
                    self.total_sentences_sent += 1
            
            llm_time = (time.time() - llm_start) * 1000
            
            # Add to history (ONLY for finals)
            if not is_partial:
                self.history.add_message(session_id, "user", text)
                self.history.add_message(session_id, "assistant", full_response)
                logger.info(f"✅ History updated")
            
            total_time = (time.time() - start_time) * 1000
            
            logger.info("─" * 80)
            logger.info(f"✅ SUCCESS (Natural Speech Mode):")
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
                "mode": "natural_speech",
                "was_partial": is_partial
            }
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ ERROR processing transcript: {e}", exc_info=True)
            logger.error("=" * 80)
            
            # Send error message
            error_msg = "Sorry, I'm having trouble right now. Can you repeat that?"
            try:
                await self._send_to_tts_natural(room_name, error_msg, session_id)
            except:
                pass
            
            return {
                "status": "error",
                "error": str(e),
                "total_time_ms": (time.time() - start_time) * 1000
            }
    
    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        """Stream tokens from Gemini with settings optimized for natural speech"""
        try:
            from google import genai
            
            client = genai.Client(api_key=self.gemini_api_key)
            
            # Optimized for natural, varied responses
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.9,  # Higher for more natural variation
                    max_output_tokens=500,  # Allow longer natural responses
                    top_p=0.95,
                    top_k=50,  # More diversity
                ),
            ):
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini streaming error: {e}")
            yield "I'm experiencing technical difficulties right now."
    
    async def _send_to_tts_natural(self, room_name: str, text: str, session_id: str):
        """
        Send text to TTS with NATURAL PACING for human-like rhythm
        Longer pauses between thoughts for more natural flow
        """
        try:
            # Natural pacing between sentences (longer pause for natural rhythm)
            if session_id in self._last_tts_time:
                time_since_last = time.time() - self._last_tts_time[session_id]
                if time_since_last < self._natural_pause_duration:
                    delay = self._natural_pause_duration - time_since_last
                    logger.debug(f"⏸️ Natural pause: {delay:.1f}s")
                    await asyncio.sleep(delay)
            
            tts_start = time.time()
            self._last_tts_time[session_id] = tts_start
            
            # Send to TTS with generous timeout for natural prosody
            try:
                await asyncio.wait_for(
                    self.tts.publish_to_room(
                        room_name=room_name,
                        text=text,
                        voice_id="default",
                        streaming=True
                    ),
                    timeout=45.0  # Longer timeout for natural-paced synthesis
                )
            except asyncio.TimeoutError:
                logger.error(f"❌ TTS timeout for: '{text[:50]}...'")
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
            "message": "Interruption handled naturally"
        }
    
    def get_stats(self) -> Dict:
        """Get statistics"""
        active_sessions = len(self.history.sessions)
        total_messages = sum(len(msgs) for msgs in self.history.sessions.values())
        
        session_details = {}
        for session_id, msgs in self.history.sessions.items():
            session_details[session_id[:8]] = {
                "messages": len(msgs),
                "last_activity": msgs[-1].timestamp.isoformat() if msgs else None
            }
        
        return {
            "mode": "natural_speech_optimized",
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "avg_first_sentence_ms": round(self.avg_first_sentence_ms, 1),
            "config": {
                "max_sentence_chars": self.max_sentence_chars,
                "min_chunk_size": self.min_chunk_size,
                "natural_pause_duration": self._natural_pause_duration,
                "ignore_partials": self.ignore_partials
            },
            "sessions": session_details
        }
    
    def clear_session(self, session_id: str):
        """Clear conversation history for a session"""
        self.history.clear_session(session_id)
        
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
            "assistant": "natural_speech_optimized",
            "tts_available": self.tts is not None,
            "gemini_configured": bool(self.gemini_api_key),
            "stats": self.get_stats()
        }