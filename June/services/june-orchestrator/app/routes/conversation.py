"""Conversational AI Routes for ChatGPT-style interaction"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging

from ..services.conversational_ai_processor import (
    ConversationalAIProcessor,
    ConversationRequest,
    ConversationResponse
)
from ..services.conversation_memory_service import ConversationMemoryService
from ..core.dependencies import (
    conversational_ai_processor_dependency,
    conversation_memory_service_dependency,
    get_current_user
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Request/Response models
class ChatMessage(BaseModel):
    session_id: str
    message: str
    audio_data: Optional[str] = None
    context_hint: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_state: str
    context_references: List[str] = []
    followup_suggestions: List[str] = []
    topics_discussed: List[str] = []
    response_metadata: Dict[str, Any] = {}

class ConversationHistoryResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]
    total_messages: int
    conversation_patterns: Dict[str, Any] = {}

class ConversationInsightsResponse(BaseModel):
    session_id: str
    insights: Dict[str, Any]


@router.post("/chat", response_model=ChatResponse)
async def chat_conversation(
    chat_request: ChatMessage,
    processor: ConversationalAIProcessor = Depends(conversational_ai_processor_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Main conversational AI endpoint - ChatGPT-style interaction"""
    try:
        # Convert to internal request format
        request = ConversationRequest(
            session_id=chat_request.session_id,
            user_id=current_user.get("sub", "anonymous"),
            message=chat_request.message,
            audio_data=chat_request.audio_data,
            context_hint=chat_request.context_hint
        )
        
        # Process conversation
        response = await processor.process_conversation(request)
        
        logger.info(
            f"[CHAT] Processed conversation for session {chat_request.session_id}: "
            f"state={response.conversation_state}, topics={response.topics_discussed}"
        )
        
        return ChatResponse(
            response=response.response,
            conversation_state=response.conversation_state,
            context_references=response.context_references,
            followup_suggestions=response.followup_suggestions,
            topics_discussed=response.topics_discussed,
            response_metadata=response.response_metadata
        )
        
    except Exception as e:
        logger.error(f"[CHAT] Error processing conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Conversation processing failed: {str(e)}")


@router.get("/history/{session_id}", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    session_id: str,
    limit: int = 20,
    memory_service: ConversationMemoryService = Depends(conversation_memory_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Get conversation history for a session"""
    try:
        # Get conversation history
        messages = await memory_service.get_conversation_history(session_id, limit)
        
        # Convert to dict format for response
        message_dicts = []
        for msg in messages:
            message_dicts.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "intent": msg.intent,
                "topic": msg.topic,
                "tokens_used": msg.tokens_used,
                "response_time_ms": msg.response_time_ms
            })
        
        # Get conversation patterns
        patterns = await memory_service.analyze_conversation_patterns(session_id)
        
        logger.info(f"[HISTORY] Retrieved {len(message_dicts)} messages for session {session_id}")
        
        return ConversationHistoryResponse(
            session_id=session_id,
            messages=message_dicts,
            total_messages=len(message_dicts),
            conversation_patterns=patterns
        )
        
    except Exception as e:
        logger.error(f"[HISTORY] Error retrieving history for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve conversation history: {str(e)}")


@router.get("/insights/{session_id}", response_model=ConversationInsightsResponse)
async def get_conversation_insights(
    session_id: str,
    processor: ConversationalAIProcessor = Depends(conversational_ai_processor_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Get detailed insights about a conversation session"""
    try:
        insights = await processor.get_conversation_insights(session_id)
        
        logger.info(f"[INSIGHTS] Generated insights for session {session_id}")
        
        return ConversationInsightsResponse(
            session_id=session_id,
            insights=insights
        )
        
    except Exception as e:
        logger.error(f"[INSIGHTS] Error generating insights for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate insights: {str(e)}")


@router.post("/context/{session_id}/topic")
async def set_conversation_topic(
    session_id: str,
    topic: str,
    memory_service: ConversationMemoryService = Depends(conversation_memory_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Manually set the current conversation topic"""
    try:
        # Get current context
        context = await memory_service.get_context(session_id)
        if not context:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Update topic
        context.current_topic = topic
        if topic not in context.topic_history:
            context.topic_history.append(topic)
        
        await memory_service.save_context(context)
        
        logger.info(f"[TOPIC] Set topic '{topic}' for session {session_id}")
        
        return {"message": f"Topic set to '{topic}'", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"[TOPIC] Error setting topic for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set topic: {str(e)}")


@router.delete("/sessions/{session_id}")
async def clear_conversation(
    session_id: str,
    memory_service: ConversationMemoryService = Depends(conversation_memory_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Clear conversation history and context for a session"""
    try:
        # Clear conversation data (this would be implemented in the memory service)
        # For now, we'll create a new context to effectively reset
        from ..services.conversation_memory_service import ConversationContext
        
        new_context = ConversationContext(
            session_id=session_id,
            user_id=current_user.get("sub", "anonymous")
        )
        await memory_service.save_context(new_context)
        
        logger.info(f"[CLEAR] Cleared conversation for session {session_id}")
        
        return {"message": "Conversation cleared", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"[CLEAR] Error clearing conversation for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear conversation: {str(e)}")


@router.get("/stats")
async def get_conversation_stats(
    memory_service: ConversationMemoryService = Depends(conversation_memory_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    """Get overall conversation system statistics"""
    try:
        stats = memory_service.get_stats()
        
        logger.info("[STATS] Retrieved conversation system statistics")
        
        return {
            "conversation_system": "active",
            "memory_stats": stats,
            "features": {
                "context_management": True,
                "topic_tracking": True,
                "intent_recognition": True,
                "elaboration_support": True,
                "learning_adaptation": True,
                "conversation_patterns": True,
                "follow_up_suggestions": True,
                "redis_backend": True,
                "persistent_memory": True,
                "pattern_analysis": True
            }
        }
        
    except Exception as e:
        logger.error(f"[STATS] Error retrieving conversation stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")