# June/services/june-orchestrator/enhanced_conversation_manager.py
# Enhanced conversation management with TTS integration

import uuid
import json
import logging
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import asyncio

from models import User, Conversation, Message, Tool, StreamingSession, get_db
from tts_service import get_tts_service, AudioResponse, initialize_tts_service

logger = logging.getLogger(__name__)

class EnhancedConversationManager:
    """Enhanced conversation manager with TTS integration"""
    
    def __init__(self, db: Session):
        self.db = db
        self.tts_service = get_tts_service()
        
    async def initialize(self):
        """Initialize the conversation manager and TTS service"""
        tts_initialized = await initialize_tts_service()
        if tts_initialized:
            logger.info("✅ Enhanced conversation manager initialized with TTS support")
        else:
            logger.warning("⚠️ Enhanced conversation manager initialized without TTS support")
        
    async def get_or_create_user(self, keycloak_id: str, username: str, email: str = None) -> User:
        """Get existing user or create new one"""
        user = self.db.query(User).filter(User.keycloak_id == keycloak_id).first()
        
        if not user:
            user = User(
                keycloak_id=keycloak_id,
                username=username,
                email=email,
                display_name=username
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            logger.info(f"Created new user: {username} ({keycloak_id})")
        else:
            # Update last active
            user.last_active = datetime.utcnow()
            self.db.commit()
            
        return user
    
    async def create_conversation(self, user: User, title: str = None) -> Conversation:
        """Create a new conversation"""
        if not title:
            title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
        conversation = Conversation(
            user_id=user.id,
            title=title,
            status='active'
        )
        
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        
        logger.info(f"Created conversation {conversation.id} for user {user.username}")
        return conversation
    
    async def get_active_conversation(self, user: User) -> Optional[Conversation]:
        """Get the most recent active conversation for a user"""
        return self.db.query(Conversation).filter(
            Conversation.user_id == user.id,
            Conversation.status == 'active'
        ).order_by(desc(Conversation.updated_at)).first()
    
    async def get_or_create_conversation(self, user: User) -> Conversation:
        """Get active conversation or create new one"""
        conversation = await self.get_active_conversation(user)
        
        if not conversation:
            conversation = await self.create_conversation(user)
            
        return conversation
    
    async def add_message_with_audio(
        self, 
        conversation: Conversation,
        user: User,
        role: str,
        content: str,
        audio_metadata: Dict = None,
        processing_time: int = None,
        model_used: str = None,
        confidence_score: float = None,
        generate_tts: bool = False,
        user_preferences: Dict = None
    ) -> Tuple[Message, Optional[AudioResponse]]:
        """Add a message to the conversation with optional TTS generation"""
        
        # Get next sequence number
        max_seq = self.db.query(func.max(Message.sequence_number)).filter(
            Message.conversation_id == conversation.id
        ).scalar() or 0
        
        # Initialize audio metadata
        if audio_metadata is None:
            audio_metadata = {}
        
        # Generate audio if requested and it's an assistant message
        audio_response = None
        if generate_tts and role == "assistant" and content.strip():
            try:
                audio_response = await self.tts_service.synthesize_speech_for_response(
                    text=content,
                    user_preferences=user_preferences
                )
                
                # Add audio metadata
                audio_metadata.update({
                    "has_tts_audio": True,
                    "tts_provider": audio_response.provider,
                    "tts_voice_id": audio_response.voice_id,
                    "tts_processing_time_ms": audio_response.processing_time_ms,
                    "tts_cached": audio_response.cached,
                    "tts_content_type": audio_response.content_type,
                    "audio_size_bytes": len(audio_response.audio_data),
                    "text_hash": audio_response.text_hash
                })
                
                logger.info(f"🎵 Generated TTS audio for message: {len(audio_response.audio_data)} bytes")
                
            except Exception as e:
                logger.error(f"❌ TTS generation failed for message: {e}")
                audio_metadata.update({
                    "has_tts_audio": False,
                    "tts_error": str(e)
                })
        
        # Create message
        message = Message(
            conversation_id=conversation.id,
            user_id=user.id,
            role=role,
            content=content,
            audio_metadata=audio_metadata,
            sequence_number=max_seq + 1,
            processing_time=processing_time,
            model_used=model_used,
            confidence_score=confidence_score
        )
        
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        
        logger.info(f"Added {role} message to conversation {conversation.id}")
        return message, audio_response
    
    async def add_message(
        self, 
        conversation: Conversation,
        user: User,
        role: str,
        content: str,
        audio_metadata: Dict = None,
        processing_time: int = None,
        model_used: str = None,
        confidence_score: float = None
    ) -> Message:
        """Add a message to the conversation (backward compatibility)"""
        message, _ = await self.add_message_with_audio(
            conversation=conversation,
            user=user,
            role=role,
            content=content,
            audio_metadata=audio_metadata,
            processing_time=processing_time,
            model_used=model_used,
            confidence_score=confidence_score,
            generate_tts=False
        )
        return message
    
    async def process_user_message_with_audio(
        self, 
        user: User, 
        user_message: str,
        audio_metadata: Dict = None,
        generate_tts_response: bool = True,
        user_preferences: Dict = None
    ) -> Tuple[str, Dict, Optional[bytes]]:
        """Process user message and return AI response with optional audio"""
        
        start_time = datetime.now()
        
        # Get or create conversation
        conversation = await self.get_or_create_conversation(user)
        
        # Add user message (no TTS for user messages)
        user_msg, _ = await self.add_message_with_audio(
            conversation, user, "user", user_message, audio_metadata
        )
        
        # Get conversation context
        context = await self.get_conversation_context(conversation)
        
        # Generate AI response (this would integrate with your existing AI generation)
        ai_response = await self._generate_ai_response(user_message, context, conversation, user)
        
        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Add AI response with TTS generation
        ai_msg, audio_response = await self.add_message_with_audio(
            conversation=conversation, 
            user=user, 
            role="assistant", 
            content=ai_response,
            processing_time=processing_time, 
            model_used="gemini-1.5-flash",
            generate_tts=generate_tts_response,
            user_preferences=user_preferences
        )
        
        # Prepare response metadata
        response_metadata = {
            "conversation_id": str(conversation.id),
            "message_id": str(ai_msg.id),
            "processing_time": processing_time,
            "context_length": len(context),
            "has_audio": audio_response is not None
        }
        
        # Add audio metadata if available
        if audio_response:
            response_metadata.update({
                "audio_provider": audio_response.provider,
                "audio_voice_id": audio_response.voice_id,
                "audio_processing_time_ms": audio_response.processing_time_ms,
                "audio_cached": audio_response.cached,
                "audio_size_bytes": len(audio_response.audio_data),
                "audio_content_type": audio_response.content_type
            })
        
        # Return text response, metadata, and audio bytes
        audio_bytes = audio_response.audio_data if audio_response else None
        
        return ai_response, response_metadata, audio_bytes
    
    async def _generate_ai_response(self, user_message: str, context: List[Dict], conversation: Conversation, user: User) -> str:
        """Generate AI response (placeholder - integrate with your existing AI generation)"""
        
        # This is where you'd integrate with your existing Gemini AI generation
        # For now, providing a basic response that acknowledges TTS capability
        
        responses = [
            f"I understand you said: '{user_message}'. I'm June, your AI assistant, and I can now respond with voice!",
            f"Thanks for your message: '{user_message}'. I'm here to help with voice responses enabled.",
            f"I heard you say: '{user_message}'. How can I assist you today?",
            f"Your message '{user_message}' has been received. I can now provide audio responses!"
        ]
        
        # Simple response selection based on message content
        if "hello" in user_message.lower() or "hi" in user_message.lower():
            return "Hello! I'm June, your AI assistant. I can now respond with voice audio. How can I help you today?"
        elif "how are you" in user_message.lower():
            return "I'm doing great! I've just been upgraded with voice capabilities. I can now speak my responses to you."
        elif "what can you do" in user_message.lower():
            return "I can help you with various tasks and now I can respond with voice audio! Ask me anything and I'll speak my response back to you."
        else:
            # Use context length to vary response
            response_index = len(context) % len(responses)
            return responses[response_index]
    
    async def get_conversation_context(self, conversation: Conversation, max_messages: int = 10) -> List[Dict]:
        """Get recent conversation context for AI"""
        messages = self.db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(desc(Message.created_at)).limit(max_messages).all()
        
        # Reverse to chronological order
        messages.reverse()
        
        context = []
        for msg in messages:
            context.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "confidence": msg.confidence_score,
                "has_audio": msg.audio_metadata.get("has_tts_audio", False)
            })
            
        return context
    
    async def regenerate_audio_for_message(
        self, 
        message_id: str, 
        voice: str = None, 
        speed: float = None,
        user_preferences: Dict = None
    ) -> Optional[AudioResponse]:
        """Regenerate TTS audio for an existing message"""
        
        # Get the message
        message = self.db.query(Message).filter(Message.id == message_id).first()
        
        if not message or message.role != "assistant":
            raise ValueError("Message not found or not an assistant message")
        
        try:
            # Generate new audio
            audio_response = await self.tts_service.synthesize_speech_for_response(
                text=message.content,
                voice=voice,
                speed=speed,
                user_preferences=user_preferences
            )
            
            # Update message metadata
            audio_metadata = message.audio_metadata or {}
            audio_metadata.update({
                "has_tts_audio": True,
                "tts_provider": audio_response.provider,
                "tts_voice_id": audio_response.voice_id,
                "tts_processing_time_ms": audio_response.processing_time_ms,
                "tts_cached": audio_response.cached,
                "tts_content_type": audio_response.content_type,
                "audio_size_bytes": len(audio_response.audio_data),
                "text_hash": audio_response.text_hash,
                "regenerated_at": datetime.utcnow().isoformat()
            })
            
            message.audio_metadata = audio_metadata
            self.db.commit()
            
            logger.info(f"🔄 Regenerated TTS audio for message {message_id}")
            return audio_response
            
        except Exception as e:
            logger.error(f"❌ Failed to regenerate audio for message {message_id}: {e}")
            raise RuntimeError(f"Audio regeneration failed: {e}")
    
    async def clone_voice_for_message(
        self,
        message_id: str,
        reference_audio_bytes: bytes
    ) -> Optional[AudioResponse]:
        """Generate voice-cloned audio for an existing message"""
        
        # Get the message
        message = self.db.query(Message).filter(Message.id == message_id).first()
        
        if not message or message.role != "assistant":
            raise ValueError("Message not found or not an assistant message")
        
        try:
            # Generate cloned audio
            audio_response = await self.tts_service.clone_voice_for_response(
                text=message.content,
                reference_audio_bytes=reference_audio_bytes
            )
            
            # Update message metadata
            audio_metadata = message.audio_metadata or {}
            audio_metadata.update({
                "has_tts_audio": True,
                "tts_provider": audio_response.provider,
                "tts_voice_id": audio_response.voice_id,
                "tts_processing_time_ms": audio_response.processing_time_ms,
                "tts_cached": audio_response.cached,
                "tts_content_type": audio_response.content_type,
                "audio_size_bytes": len(audio_response.audio_data),
                "text_hash": audio_response.text_hash,
                "voice_cloned_at": datetime.utcnow().isoformat()
            })
            
            message.audio_metadata = audio_metadata
            self.db.commit()
            
            logger.info(f"🎤 Generated voice-cloned audio for message {message_id}")
            return audio_response
            
        except Exception as e:
            logger.error(f"❌ Failed to generate voice-cloned audio for message {message_id}: {e}")
            raise RuntimeError(f"Voice cloning failed: {e}")
    
    async def get_tts_status(self) -> Dict[str, Any]:
        """Get TTS service status"""
        return await self.tts_service.get_service_status()
    
    async def get_available_voices(self, language: str = None) -> Dict[str, Any]:
        """Get available TTS voices"""
        return await self.tts_service.get_available_voices(language)
    
    # Backward compatibility methods from original ConversationManager
    async def update_conversation_summary(self, conversation: Conversation, summary: str):
        """Update conversation summary"""
        conversation.summary = summary
        conversation.updated_at = datetime.utcnow()
        self.db.commit()
    
    async def end_conversation(self, conversation: Conversation):
        """Mark conversation as ended"""
        conversation.status = 'completed'
        conversation.ended_at = datetime.utcnow()
        self.db.commit()
        logger.info(f"Ended conversation {conversation.id}")
    
    async def get_user_conversations(self, user: User, limit: int = 20) -> List[Conversation]:
        """Get user's conversation history"""
        return self.db.query(Conversation).filter(
            Conversation.user_id == user.id
        ).order_by(desc(Conversation.updated_at)).limit(limit).all()