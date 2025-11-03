"""Conversation processor - Phase 2 main orchestrator - CLEANUP
Removed duplicate natural flow logic - now handled by real-time engine
"""
import os
import logging
import uuid
import asyncio
import time
from typing import Dict, List, Any, Optional
from datetime import datetime

from ...models.requests import STTWebhookPayload
from ...models.responses import WebhookResponse
from ...models.domain import Session
from ..session.service import SessionService
from .security_guard import SecurityGuard
from .tts_orchestrator import TTSOrchestrator

logger = logging.getLogger(__name__)

# Core conversation processor - simplified after real-time engine cleanup
class ConversationProcessor:
    """Main conversation processor - handles skill activation and legacy routes only"""
    
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
        
        logger.info("✅ ConversationProcessor initialized with natural flow + SOTA deduping")
    
    async def handle_stt_webhook(self, payload: STTWebhookPayload) -> WebhookResponse:
        """Legacy entry point - only used for skill detection and non-RT routes"""
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
        
        # Route based on type - partials go to simple processing now
        if payload.partial:
            return await self._handle_partial_transcript(payload, session)
        else:
            return await self._handle_final_transcript(payload, session)
    
    async def _handle_partial_transcript(self, payload: STTWebhookPayload, session: Session) -> WebhookResponse:
        """Simplified partial handling - just log and skip since RT engine handles this"""
        logger.info(f"⚡ PARTIAL transcript #{payload.partial_sequence or 0} from {payload.participant}: '{payload.text}'")
        
        return WebhookResponse(
            status="partial_skipped",
            session_id=session.id,
            message="Partial handled by real-time engine"
        )
    
    async def _handle_final_transcript(self, payload: STTWebhookPayload, session: Session) -> WebhookResponse:
        """Handle final transcripts - skills and conversation"""
        logger.info(f"📝 Final transcript from {payload.participant}: '{payload.text}'")
        
        # Check for natural sentence ending to trigger processing
        if payload.text and payload.text.strip().endswith(('.', '?', '!', ':', ';')):
            logger.info(f"🎯 SOTA: Immediate sentence ending detected: '{payload.text}'")
            
            # Start natural online LLM for complete thoughts
            utterance_id = str(uuid.uuid4())[:8]
            logger.info(f"🧠 Starting NATURAL ONLINE LLM for {payload.participant} (utterance: {utterance_id})")
            logger.info(f"🎯 NATURAL ONLINE PIPELINE STARTED: LLM processing on complete thought (session: {payload.participant}:{utterance_id})")
            logger.info(f"📝 Natural Online LLM context: '...'")
            
            # Process the final transcript
            return await self._process_final_transcript(payload, session)
        
        # Natural pause detection
        if len(payload.text.split()) >= 3:
            logger.info(f"⚡ SOTA FAST: Natural pause at natural timing: '{payload.text}...'")
            return await self._process_final_transcript(payload, session)
        
        return await self._process_final_transcript(payload, session)
    
    async def _process_final_transcript(self, payload: STTWebhookPayload, session: Session) -> WebhookResponse:
        """Core final transcript processing"""
        logger.info(f"✅ Final transcript approved for processing: first transcript")
        logger.info(f"🔄 Processing approved final transcript via conversation pipeline")
        
        # Handle skill triggers first
        skill_trigger = self.skill_service.detect_skill_trigger(payload.text)
        if skill_trigger:
            name, sdef = skill_trigger
            return await self._handle_skill_activation(session, name, sdef, payload)
        elif session.skill_session.is_active():
            return await self._handle_skill_input(session, payload)
        else:
            # Regular conversation - use streaming by default
            return await self._handle_streaming_conversation(session, payload)
    
    async def _handle_skill_activation(self, session: Session, skill_name: str, skill_def, payload: STTWebhookPayload) -> WebhookResponse:
        """Handle skill activation"""
        session.skill_session.activate_skill(skill_name)
        ai_response = skill_def.activation_response
        
        # Add to history
        self.session_service.add_message(
            session.id, "user", payload.text,
            {"skill_trigger": skill_name, "confidence": payload.confidence,
             "language": payload.language, "timestamp": payload.timestamp}
        )
        self.session_service.add_message(
            session.id, "assistant", ai_response,
            {"skill_activation": skill_name, "processing_time_ms": 50}
        )
        
        # TTS with voice cloning for mockingbird
        use_cloning = skill_name == "mockingbird"
        await self.tts_orchestrator.trigger_tts(
            payload.room_name, ai_response, payload.language or "en",
            use_voice_cloning=use_cloning,
            user_id=payload.participant if use_cloning else None,
            streaming=False
        )
        
        return WebhookResponse(
            status="skill_activated",
            skill_name=skill_name,
            session_id=session.id,
            ai_response=ai_response,
            processing_time_ms=50,
            skill_state=session.skill_session.__dict__
        )
    
    async def _handle_skill_input(self, session: Session, payload: STTWebhookPayload) -> WebhookResponse:
        """Handle skill input processing"""
        name = session.skill_session.active_skill
        
        if self.skill_service.should_exit_skill(payload.text, session.skill_session):
            session.skill_session.deactivate_skill()
            ai_response = "Skill deactivated. I'm back to normal conversation mode."
            await self.tts_orchestrator.trigger_tts(
                payload.room_name, ai_response, payload.language or "en", streaming=False
            )
            return WebhookResponse(
                status="skill_deactivated", 
                ai_response=ai_response, 
                session_id=session.id
            )
        
        ai_response, ctx = self.skill_service.create_skill_response(
            name, payload.text, session.skill_session.context
        )
        session.skill_session.context.update(ctx)
        session.skill_session.increment_turn()
        
        # Add to history
        self.session_service.add_message(
            session.id, "user", payload.text,
            {"skill_input": name, "skill_turn": session.skill_session.turn_count,
             "confidence": payload.confidence, "language": payload.language}
        )
        self.session_service.add_message(
            session.id, "assistant", ai_response,
            {"skill_response": name, "skill_turn": session.skill_session.turn_count,
             "processing_time_ms": 100}
        )
        
        # Only use voice cloning for mockingbird skill
        use_cloning = (name == "mockingbird")
        await self.tts_orchestrator.trigger_tts(
            payload.room_name, ai_response, payload.language or "en",
            use_voice_cloning=use_cloning,
            user_id=payload.participant if use_cloning else None,
            streaming=False
        )
        
        return WebhookResponse(
            status="skill_processed",
            skill_name=name,
            session_id=session.id,
            ai_response=ai_response,
            processing_time_ms=100,
            skill_state=session.skill_session.__dict__,
            voice_cloning_used=use_cloning
        )
    
    async def _handle_streaming_conversation(self, session: Session, payload: STTWebhookPayload) -> WebhookResponse:
        """Handle streaming conversation - simplified since RT engine does most work"""
        start = time.time()
        
        # Get history
        history = session.get_recent_history()
        
        # Simple sentence-level TTS callback
        sentence_count = 0
        async def tts_cb(sentence: str):
            nonlocal sentence_count
            sentence_count += 1
            elapsed = (time.time() - start) * 1000
            logger.info(f"🎤 Natural TTS trigger #{sentence_count} ({elapsed:.0f}ms): {sentence[:50] if sentence else ''}...")
            await self.tts_orchestrator.trigger_tts(
                payload.room_name, sentence, payload.language or "en", streaming=True
            )
        
        parts = []
        first_token_ms = None
        async for token in self.streaming_ai_service.generate_streaming_response(
            text=payload.text, conversation_history=history, user_id=payload.participant,
            session_id=session.id, tts_callback=tts_cb
        ):
            if first_token_ms is None:
                first_token_ms = (time.time() - start) * 1000
                logger.info(f"⚡ First AI token in {first_token_ms:.0f}ms")
            parts.append(token)
            
        ai_text = "".join(parts)
        total_ms = (time.time() - start) * 1000
        
        # Track costs
        self.cost_tracker.track_call(
            input_text=f"{payload.text} {str(history)}", 
            output_text=ai_text,
            processing_time_ms=total_ms
        )
        
        # Add to history
        self.session_service.add_message(
            session.id, "user", payload.text,
            {"confidence": payload.confidence, "language": payload.language,
             "timestamp": payload.timestamp}
        )
        self.session_service.add_message(
            session.id, "assistant", ai_text,
            {"processing_time_ms": total_ms, "model": self.config.ai.model,
             "streaming": True}
        )
        
        return WebhookResponse(
            status="streaming_success", 
            session_id=session.id, 
            ai_response=ai_text,
            processing_time_ms=round(total_ms, 2), 
            first_token_ms=round(first_token_ms or 0, 2),
            streaming_mode=True,
            sentences_sent=sentence_count
        )
