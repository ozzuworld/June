"""
Simple Voice Assistant - Natural Conversation
STT → LLM → TTS with minimal overhead

This replaces:
- RealTimeConversationEngine
- StreamingAIService  
- UltraFastPhraseBuffer
- SmartTTSQueue
- ai_service.py
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
    
    def __init__(self, max_turns: int = 3):
        self.sessions: Dict[str, List[Message]] = {}
        self.max_turns = max_turns  # Keep last N exchanges (2N messages)
        logger.info(f"✅ ConversationHistory initialized (max_turns={max_turns})")
    
    def add_message(self, session_id: str, role: str, content: str):
        """Add message and auto-trim old history"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        
        self.sessions[session_id].append(
            Message(role=role, content=content, timestamp=datetime.utcnow())
        )
        
        # Keep only last N exchanges (user+assistant pairs)
        max_messages = self.max_turns * 2
        if len(self.sessions[session_id]) > max_messages:
            old_count = len(self.sessions[session_id])
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]
            logger.debug(f"🗑️ Trimmed history for {session_id}: {old_count} → {max_messages} messages")
    
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
            del self.sessions[session_id]
            logger.info(f"🗑️ Cleared history for session {session_id}")


class SimpleVoiceAssistant:
    """
    Minimal voice assistant with natural conversation flow
    
    Key principles:
    1. Only process FINAL transcripts (buffer short partials)
    2. Stream LLM response in sentence chunks
    3. Send to TTS immediately when sentence completes
    4. Keep conversation history small (last 3 exchanges)
    """
    
    def __init__(self, gemini_api_key: str, tts_service):
        self.gemini_api_key = gemini_api_key
        self.tts = tts_service
        self.history = ConversationHistory(max_turns=3)
        
        # Simple sentence detection - matches . ! ? and their variants
        self.sentence_end = re.compile(r'[.!?。！？]+\s*')
        
        # Metrics
        self.total_requests = 0
        self.total_sentences_sent = 0
        self.avg_first_sentence_ms = 0
        
        logger.info("=" * 80)
        logger.info("✅ Simple Voice Assistant initialized")
        logger.info("   - Mode: Direct STT → LLM → TTS")
        logger.info("   - History: Last 3 exchanges")
        logger.info("   - Sentence chunking: Regex-based")
        logger.info("   - No buffering queues")
        logger.info("=" * 80)
    
    def _build_prompt(self, user_message: str, history: List[Dict]) -> str:
        """Build natural conversation prompt"""
        
        system = """You are June, a helpful voice assistant.

CRITICAL RULES FOR VOICE:
1. Keep responses SHORT (1-3 sentences max)
2. Use natural, conversational language
3. Never repeat what you just said
4. If you already answered something, acknowledge briefly: "As I mentioned..." or "Like I said..."
5. Don't use lists or bullet points - speak naturally

Examples:
User: "What's the weather?"
You: "It's sunny and 72 degrees today."

User: "What about tomorrow?"
You: "Tomorrow should be partly cloudy with a high of 68."

User: "Thanks!"
You: "You're welcome! Anything else?"

Remember: This is VOICE, not text. Be brief and natural!"""
        
        # Format conversation history
        if history:
            context_lines = []
            for msg in history:
                role = "User" if msg['role'] == 'user' else "You"
                context_lines.append(f"{role}: {msg['content']}")
            
            context = "\n".join(context_lines)
            prompt = f"{system}\n\nConversation:\n{context}\n\nUser: {user_message}\nYou:"
        else:
            prompt = f"{system}\n\nUser: {user_message}\nYou:"
        
        return prompt
    
    async def handle_transcript(
        self,
        session_id: str,
        room_name: str,
        text: str,
        is_partial: bool = False
    ) -> Dict:
        """
        Main entry point for STT transcripts
        
        Returns metrics dict for monitoring
        """
        start_time = time.time()
        self.total_requests += 1
        
        # Skip tiny partials (less than 2 words or 8 characters)
        word_count = len(text.strip().split())
        char_count = len(text.strip())
        
        if is_partial:
            if word_count < 2 or char_count < 8:
                logger.debug(f"⏸️ Buffering partial: '{text}' ({word_count} words, {char_count} chars)")
                return {
                    "status": "buffering",
                    "reason": "partial_too_short",
                    "word_count": word_count,
                    "char_count": char_count
                }
            else:
                logger.info(f"🚀 Processing long partial: '{text[:30]}...' ({word_count} words)")
        
        # Log what we're processing
        status = "PARTIAL" if is_partial else "FINAL"
        logger.info("=" * 80)
        logger.info(f"📥 [{status}] Session: {session_id[:8]}")
        logger.info(f"📝 Text: '{text[:100]}...'")
        logger.info(f"📊 Words: {word_count}, Chars: {char_count}")
        
        try:
            # Get conversation history
            history = self.history.get_history(session_id)
            logger.info(f"📚 History: {len(history)} messages")
            
            # Build prompt
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
                    # Extract sentence up to and including punctuation
                    sentence = sentence_buffer[:match.end()].strip()
                    sentence_buffer = sentence_buffer[match.end():]
                    
                    if sentence:  # Non-empty sentence
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
                        
                        # Send to TTS immediately (fire and forget)
                        logger.info(f"🔊 Sentence #{sentence_count}: '{sentence[:50]}...'")
                        asyncio.create_task(
                            self._send_to_tts(room_name, sentence, session_id)
                        )
                        self.total_sentences_sent += 1
            
            # Send any remaining text as final fragment
            if sentence_buffer.strip():
                sentence_count += 1
                logger.info(f"🔊 Final fragment: '{sentence_buffer[:50]}...'")
                asyncio.create_task(
                    self._send_to_tts(room_name, sentence_buffer.strip(), session_id)
                )
                self.total_sentences_sent += 1
            
            llm_time = (time.time() - llm_start) * 1000
            
            # Add to history (ONLY for finals, not partials)
            if not is_partial:
                self.history.add_message(session_id, "user", text)
                self.history.add_message(session_id, "assistant", full_response)
                logger.info(f"💾 Added to history (now {len(self.history.get_history(session_id))} messages)")
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
            asyncio.create_task(self._send_to_tts(room_name, error_msg, session_id))
            
            return {
                "status": "error",
                "error": str(e),
                "total_time_ms": (time.time() - start_time) * 1000
            }
    
    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        """
        Stream tokens from Gemini
        
        Uses gemini-2.0-flash-exp for best latency
        Falls back to gemini-2.0-flash if needed
        """
        try:
            from google import genai
            
            client = genai.Client(api_key=self.gemini_api_key)
            
            logger.debug("🌐 Connecting to Gemini API...")
            
            # Stream with optimized settings for voice
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',  # Fastest model
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.7,           # Natural but consistent
                    max_output_tokens=250,     # ~50 words (2-3 sentences)
                    top_p=0.9,
                    top_k=40,
                ),
            ):
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini streaming error: {e}")
            
            # Fallback to stable model
            logger.info("🔄 Falling back to gemini-2.0-flash...")
            
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_api_key)
                
                for chunk in client.models.generate_content_stream(
                    model='gemini-2.0-flash',
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=250
                    ),
                ):
                    if chunk.text:
                        yield chunk.text
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties."
    
    async def _send_to_tts(self, room_name: str, text: str, session_id: str):
        """Send text to TTS service (fire and forget)"""
        try:
            tts_start = time.time()
            
            await self.tts.publish_to_room(
                room_name=room_name,
                text=text,
                voice_id="default",  # Use default XTTS voice
                streaming=True
            )
            
            tts_time = (time.time() - tts_start) * 1000
            logger.debug(f"   TTS completed in {tts_time:.0f}ms")
            
        except Exception as e:
            logger.error(f"❌ TTS error for session {session_id}: {e}")
    
    async def handle_interruption(self, session_id: str, room_name: str):
        """
        Handle user interruption (voice onset detection)
        
        In this simple version, we don't need complex logic since:
        1. TTS is already streaming (fast)
        2. LLM streaming will complete naturally
        3. Next user input will override in LiveKit
        """
        logger.info(f"🛑 User interrupted session {session_id}")
        
        # Could add logic here to:
        # - Cancel pending TTS tasks (if we tracked them)
        # - Stop LLM streaming (if we tracked it)
        # - Clear queues (we don't have any)
        
        return {
            "status": "interrupted",
            "session_id": session_id,
            "message": "Interruption handled naturally by streaming"
        }
    
    def get_stats(self) -> Dict:
        """Get simple statistics"""
        active_sessions = len(self.history.sessions)
        total_messages = sum(len(msgs) for msgs in self.history.sessions.values())
        
        return {
            "mode": "simple_voice_assistant",
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "total_requests": self.total_requests,
            "total_sentences_sent": self.total_sentences_sent,
            "avg_first_sentence_ms": round(self.avg_first_sentence_ms, 1),
            "sessions": {
                session_id: len(msgs)
                for session_id, msgs in self.history.sessions.items()
            }
        }
    
    def clear_session(self, session_id: str):
        """Clear conversation history for a session"""
        self.history.clear_session(session_id)
    
    async def health_check(self) -> Dict:
        """Health check endpoint"""
        return {
            "healthy": True,
            "assistant": "simple_voice_assistant",
            "tts_available": self.tts is not None,
            "gemini_configured": bool(self.gemini_api_key),
            "stats": self.get_stats()
        }