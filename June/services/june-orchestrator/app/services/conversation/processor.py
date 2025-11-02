"""Conversation processor - Phase 2 main orchestrator with SOTA deduping
Prevents double responses by coordinating partial-triggered online LLM and final transcripts
"""
import os
import logging
import uuid
import asyncio
import time
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime

from ...models.requests import STTWebhookPayload
from ...models.responses import WebhookResponse
from ...models.domain import Session
from ..session.service import SessionService
from .natural_flow import (
    UtteranceStateManager, FinalTranscriptTracker, SentenceBuffer,
    should_start_online_llm, should_process_final_transcript
)
from .security_guard import SecurityGuard
from .tts_orchestrator import TTSOrchestrator

logger = logging.getLogger(__name__)

# Feature flags (extracted from original webhooks.py)
STREAMING_ENABLED = os.getenv("ORCH_STREAMING_ENABLED", "true").lower() == "true"
CONCURRENT_TTS_ENABLED = os.getenv("CONCURRENT_TTS_ENABLED", "true").lower() == "true"
PARTIAL_SUPPORT_ENABLED = os.getenv("PARTIAL_SUPPORT_ENABLED", "true").lower() == "true"
ONLINE_LLM_ENABLED = os.getenv("ONLINE_LLM_ENABLED", "true").lower() == "true"

# NEW: SOTA Deduping/Coordination flags
FINAL_CANCELS_PARTIAL = os.getenv("FINAL_CANCELS_PARTIAL", "true").lower() == "true"
BLOCK_FINAL_IF_PARTIAL_ACTIVE = os.getenv("BLOCK_FINAL_IF_PARTIAL_ACTIVE", "true").lower() == "true"
DISABLE_PARTIAL_LLM_TRIGGERS = os.getenv("DISABLE_PARTIAL_LLM_TRIGGERS", "false").lower() == "true"


class OnlineLLMSession:
    """Manages online LLM processing with natural conversation flow"""
    
    def __init__(self, session_id: str, user_id: str, utterance_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.utterance_id = utterance_id
        self.partial_buffer = []
        self.llm_task: Optional[asyncio.Task] = None
        self.started_at = datetime.utcnow()
        self.first_token_sent = False
        self.accumulated_response = ""
        self.sentence_buffer = SentenceBuffer()
        # NEW: track whether this session produced audio already
        self.response_started = False
        # NEW: capture the initial partial that triggered
        self.initial_partial = None
        
    def add_partial(self, text: str, sequence: int) -> bool:
        """Add partial transcript and return if LLM should continue"""
        if not self.partial_buffer or len(text) > len(self.partial_buffer[-1]) + 3:
            self.partial_buffer.append(text)
            return True
        return False
        
    def get_context_text(self) -> str:
        """Get accumulated partial context for LLM"""
        return self.partial_buffer[-1] if self.partial_buffer else ""
        
    def is_active(self) -> bool:
        """Check if online session is still active"""
        return self.llm_task and not self.llm_task.done()
        
    def cancel(self):
        """Cancel online LLM processing"""
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()


class ConversationProcessor:
    """Main conversation processor - orchestrates the entire STT -> AI -> TTS pipeline"""
    
    def __init__(
        self, 
        session_service: SessionService,
        security_guard: SecurityGuard,
        tts_orchestrator: TTSOrchestrator,
        ai_service,
        streaming_ai_service,
        skill_service,
        cost_tracker,
        config
    ):
        self.session_service = session_service
        self.security_guard = security_guard
        self.tts_orchestrator = tts_orchestrator
        self.ai_service = ai_service
        self.streaming_ai_service = streaming_ai_service
        self.skill_service = skill_service
        self.cost_tracker = cost_tracker
        self.config = config
        
        # Natural flow managers
        self.utterance_manager = UtteranceStateManager()
        self.final_tracker = FinalTranscriptTracker()
        
        # Online LLM sessions
        self.online_sessions: Dict[str, OnlineLLMSession] = {}
        
        logger.info("✅ ConversationProcessor initialized with natural flow + SOTA deduping")
    
    async def handle_stt_webhook(self, payload: STTWebhookPayload) -> WebhookResponse:
        """Main entry point for STT webhook processing"""
        logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
        
        # Security guards
        self.security_guard.ensure_rate_limit(payload.participant)
        self.security_guard.ensure_circuit_closed()
        
        # Get or create session
        session = await self.session_service.get_or_create_for_room(
            payload.room_name, payload.participant
        )
        
        # Duplicate protection
        if payload.transcript_id:
            if not self.security_guard.ensure_not_duplicate(
                session.id, payload.transcript_id, payload.text, 
                payload.participant, payload.timestamp
            ):
                return WebhookResponse(
                    status="duplicate_blocked", 
                    message="Duplicate message blocked",
                    session_id=session.id
                )
        
        # Route based on partial vs final
        if payload.partial and PARTIAL_SUPPORT_ENABLED and ONLINE_LLM_ENABLED and not DISABLE_PARTIAL_LLM_TRIGGERS:
            return await self._handle_partial_transcript(payload, session)
        else:
            return await self._handle_final_transcript(payload, session)
    
    async def _handle_partial_transcript(self, payload: STTWebhookPayload, session: Session) -> WebhookResponse:
        """Handle partial transcripts with natural conversation flow"""
        logger.info(f"⚡ PARTIAL transcript #{payload.partial_sequence or 0} from {payload.participant}: '{payload.text}'")
        
        # Clean up expired states periodically
        self._cleanup_expired_states()
        
        # Generate utterance tracking
        utterance_id = payload.utterance_id or str(uuid.uuid4())
        session_key = f"{payload.participant}:{utterance_id}"
        
        # Add to utterance state
        significant_change = self.utterance_manager.add_partial(
            payload.participant, utterance_id, payload.text, 
            payload.partial_sequence or 1, payload.confidence or 0.0
        )
        
        if not significant_change:
            return WebhookResponse(
                status="partial_ignored",
                session_id=session.id,
                utterance_id=utterance_id,
                message="Partial ignored - no significant change"
            )
        
        # Check if we should start natural online LLM processing
        should_start = should_start_online_llm(
            self.utterance_manager, payload.participant, utterance_id, 
            payload.text, payload.confidence or 0.0
        )
        
        if session_key not in self.online_sessions and should_start:
            # Mark processing as started
            self.utterance_manager.mark_processing_started(payload.participant, utterance_id)
            
            # Start new natural online LLM session
            history = session.get_recent_history()
            
            online_session = await self._start_online_llm_processing(
                session_key, payload, session, history
            )
            online_session.initial_partial = payload.text
            
            self.online_sessions[session_key] = online_session
            
            logger.info(f"🎯 NATURAL ONLINE PIPELINE STARTED: LLM processing on complete thought (session: {session_key[:16]})")
            
            return WebhookResponse(
                status="natural_online_llm_started",
                session_id=session.id,
                utterance_id=utterance_id,
                partial_sequence=payload.partial_sequence,
                message="Natural online LLM started on complete thought",
                pipeline_mode="natural: speech-in + thinking + speech-out",
                trigger_reason="natural conversation boundary detected"
            )
            
        elif session_key in self.online_sessions:
            # Update existing online session with new partial
            online_session = self.online_sessions[session_key]
            
            if online_session.add_partial(payload.text, payload.partial_sequence or 0):
                logger.debug(f"🔄 Updated natural online context for {session_key[:16]} with partial #{payload.partial_sequence}")
                
            return WebhookResponse(
                status="partial_processed",
                session_id=session.id,
                utterance_id=utterance_id,
                partial_sequence=payload.partial_sequence,
                online_active=online_session.is_active(),
                message="Partial added to natural online context"
            )
        
        else:
            # Partial received but waiting for natural conversation boundary
            logger.debug(f"🕰️ Natural flow: waiting for complete thought - '{payload.text}'")
            
            return WebhookResponse(
                status="natural_partial_queued",
                session_id=session.id,
                utterance_id=utterance_id,
                partial_sequence=payload.partial_sequence,
                message="Partial queued, waiting for natural conversation boundary",
                waiting_for="complete thought, question, or natural pause"
            )
    
    async def _handle_final_transcript(self, payload: STTWebhookPayload, session: Session) -> WebhookResponse:
        """Handle final transcripts with natural flow gating + SOTA deduping"""
        logger.info(f"📝 Final transcript from {payload.participant}: '{payload.text}'")
        
        # Apply natural flow to final transcripts
        should_process, reason = should_process_final_transcript(
            self.final_tracker, payload.participant, payload.text, payload.confidence or 0.0
        )
        
        if not should_process:
            logger.info(f"🚫 Final transcript filtered: {reason}")
            return WebhookResponse(
                status="final_transcript_filtered",
                reason=reason,
                participant=payload.participant,
                message=f"Final transcript not processed: {reason}"
            )
        
        logger.info(f"✅ Final transcript approved for processing: {reason}")
        
        # NEW: SOTA Deduping - coordinate with active online session
        if payload.utterance_id:
            session_key = f"{payload.participant}:{payload.utterance_id}"
            if session_key in self.online_sessions:
                online_session = self.online_sessions[session_key]
                
                # If partial-triggered LLM is active
                if online_session.is_active():
                    # Strategy A: Cancel partial session and process final (more accurate)
                    if FINAL_CANCELS_PARTIAL:
                        logger.info(f"🛑 SOTA: Cancelling partial-triggered LLM for {session_key[:16]} in favor of FINAL")
                        online_session.cancel()
                        del self.online_sessions[session_key]
                        # Continue to regular processing below
                    else:
                        # Strategy B: Block final to avoid double response
                        if BLOCK_FINAL_IF_PARTIAL_ACTIVE:
                            logger.info(f"🚫 SOTA: Final ignored - partial LLM already active for {session_key[:16]}")
                            return WebhookResponse(
                                status="final_ignored_due_to_partial",
                                session_id=session.id,
                                utterance_id=payload.utterance_id,
                                message="Final ignored - partial-triggered LLM already responding"
                            )
                        else:
                            logger.info(f"ℹ️ SOTA: Allowing final while partial active (may cause double responses)")
                
        # Handle skill triggers and regular conversation
        skill_trigger = self.skill_service.detect_skill_trigger(payload.text)
        if skill_trigger:
            name, sdef = skill_trigger
            return await self._handle_skill_activation(session, name, sdef, payload)
        elif session.skill_session.is_active():
            return await self._handle_skill_input(session, payload)
        else:
            # Process approved final transcript via regular conversation
            logger.info(f"🔄 Processing approved final transcript via conversation pipeline")
            return await self._handle_conversation(session, payload)
    
    async def _start_online_llm_processing(
        self, session_key: str, payload: STTWebhookPayload, 
        session: Session, history: List[Dict]
    ) -> OnlineLLMSession:
        """Start online LLM processing with natural conversation flow"""
        online_session = OnlineLLMSession(
            session_id=session.id,
            user_id=payload.participant,
            utterance_id=payload.utterance_id or str(uuid.uuid4())
        )
        
        logger.info(f"🧠 Starting NATURAL ONLINE LLM for {payload.participant} (utterance: {online_session.utterance_id[:8]})")
        
        # Start streaming LLM processing
        online_session.llm_task = asyncio.create_task(
            self._process_online_llm_stream_natural(online_session, payload, session, history)
        )
        
        return online_session
    
    async def _process_online_llm_stream_natural(
        self, online_session: OnlineLLMSession, initial_payload: STTWebhookPayload,
        session: Session, history: List[Dict]
    ):
        """Process streaming LLM with natural conversation flow and sentence buffering"""
        try:
            start_time = time.time()
            first_token = True
            
            # Build context from partial
            context_text = online_session.get_context_text()
            logger.info(f"📝 Natural Online LLM context: '{context_text[:50]}...'")
            
            # TTS callback with sentence buffering
            sentence_count = 0
            async def natural_tts_callback(sentence: str):
                nonlocal sentence_count
                
                complete_sentence = online_session.sentence_buffer.add_token(sentence)
                if complete_sentence:
                    sentence_count += 1
                    elapsed = (time.time() - start_time) * 1000
                    online_session.response_started = True
                    logger.info(f"🎤 Natural TTS trigger #{sentence_count} ({elapsed:.0f}ms): {complete_sentence[:50]}...")
                    # Trigger streaming TTS for complete sentence
                    await self.tts_orchestrator.trigger_tts(
                        initial_payload.room_name, complete_sentence, 
                        initial_payload.language or "en", 
                        streaming=True, use_voice_cloning=False
                    )
            
            # Generate streaming response
            response_parts = []
            async for token in self.streaming_ai_service.generate_streaming_response(
                text=context_text,
                conversation_history=history,
                user_id=initial_payload.participant,
                session_id=session.id,
                tts_callback=natural_tts_callback if CONCURRENT_TTS_ENABLED else None
            ):
                if first_token:
                    first_token_time = (time.time() - start_time) * 1000
                    logger.info(f"⚡ NATURAL First token in {first_token_time:.0f}ms (natural timing)")
                    first_token = False
                    online_session.response_started = True
                    
                response_parts.append(token)
                online_session.accumulated_response += token
            
            full_response = "".join(response_parts)
            total_time = (time.time() - start_time) * 1000
            
            # Send any remaining buffered content
            if CONCURRENT_TTS_ENABLED:
                remaining = online_session.sentence_buffer.get_remaining()
                if remaining:
                    logger.info(f"🎤 Final TTS trigger: {remaining[:50]}...")
                    await self.tts_orchestrator.trigger_tts(
                        initial_payload.room_name, remaining, 
                        initial_payload.language or "en", 
                        streaming=True, use_voice_cloning=False
                    )
            
            logger.info(f"✅ Natural Online LLM completed: {len(full_response)} chars in {total_time:.0f}ms")
            
            # Add to session history
            self.session_service.add_message(
                session.id, "user", context_text,
                {
                    "confidence": initial_payload.confidence, 
                    "language": initial_payload.language,
                    "timestamp": initial_payload.timestamp,
                    "online_processing": True,
                    "natural_flow": True,
                    "utterance_id": online_session.utterance_id
                }
            )
            
            self.session_service.add_message(
                session.id, "assistant", full_response,
                {
                    "processing_time_ms": total_time, 
                    "model": self.config.ai.model,
                    "streaming": True,
                    "online_processing": True,
                    "natural_flow": True,
                    "sentences_sent": sentence_count
                }
            )
            
            # Track costs
            self.cost_tracker.track_call(
                input_text=f"{context_text} {str(history)}", 
                output_text=full_response,
                processing_time_ms=total_time
            )
            
            # Clean up session
            session_key = f"{initial_payload.participant}:{online_session.utterance_id}"
            if session_key in self.online_sessions:
                del self.online_sessions[session_key]
                
        except asyncio.CancelledError:
            logger.info(f"🛑 Natural Online LLM processing cancelled for {online_session.user_id}")
        except Exception as e:
            logger.error(f"❌ Natural Online LLM processing error: {e}")
    
    # ... rest of file unchanged ...
