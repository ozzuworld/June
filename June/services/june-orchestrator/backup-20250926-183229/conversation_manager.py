# June/services/june-orchestrator/conversation_manager.py
# Enhanced conversation management and tool system

import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import asyncio

from models import User, Conversation, Message, Tool, StreamingSession, get_db

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation persistence, context, and flow"""
    
    def __init__(self, db: Session):
        self.db = db
        
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
        """Add a message to the conversation"""
        
        # Get next sequence number
        max_seq = self.db.query(func.max(Message.sequence_number)).filter(
            Message.conversation_id == conversation.id
        ).scalar() or 0
        
        message = Message(
            conversation_id=conversation.id,
            user_id=user.id,
            role=role,
            content=content,
            audio_metadata=audio_metadata or {},
            sequence_number=max_seq + 1,
            processing_time=processing_time,
            model_used=model_used,
            confidence_score=confidence_score
        )
        
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        
        logger.info(f"Added {role} message to conversation {conversation.id}")
        return message
    
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
                "confidence": msg.confidence_score
            })
            
        return context
    
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


class ToolSystem:
    """Manages tool registration and execution"""
    
    def __init__(self, db: Session):
        self.db = db
        self._tool_functions = {}
        
    async def register_tool(self, name: str, display_name: str, description: str, 
                           category: str, schema: Dict, func: callable):
        """Register a tool function"""
        # Store in database
        tool = self.db.query(Tool).filter(Tool.name == name).first()
        
        if not tool:
            tool = Tool(
                name=name,
                display_name=display_name,
                description=description,
                category=category,
                schema=schema
            )
            self.db.add(tool)
            self.db.commit()
            self.db.refresh(tool)
        
        # Store function reference
        self._tool_functions[name] = func
        logger.info(f"Registered tool: {name}")
    
    async def get_available_tools(self) -> List[Tool]:
        """Get all enabled tools"""
        return self.db.query(Tool).filter(Tool.enabled == True).all()
    
    async def execute_tool(self, tool_name: str, parameters: Dict) -> Tuple[bool, Any, str]:
        """Execute a tool with parameters"""
        try:
            if tool_name not in self._tool_functions:
                return False, None, f"Tool {tool_name} not found"
            
            func = self._tool_functions[tool_name]
            result = await func(parameters) if asyncio.iscoroutinefunction(func) else func(parameters)
            
            return True, result, None
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return False, None, str(e)


# Built-in tools
class BasicTools:
    """Basic tool implementations"""
    
    @staticmethod
    def get_current_time(params: Dict) -> str:
        """Get current date and time"""
        timezone = params.get('timezone', 'UTC')
        now = datetime.now()
        return f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({timezone})"
    
    @staticmethod
    def simple_calculator(params: Dict) -> str:
        """Perform basic calculations"""
        try:
            expression = params.get('expression', '')
            # Safe evaluation (only allow basic math)
            allowed_names = {
                k: v for k, v in __builtins__.items() 
                if k in ('abs', 'round', 'min', 'max', 'sum', 'pow')
            }
            allowed_names.update({'__builtins__': {}})
            
            result = eval(expression, allowed_names)
            return f"Result: {result}"
        except Exception as e:
            return f"Calculation error: {str(e)}"
    
    @staticmethod
    def set_reminder(params: Dict) -> str:
        """Set a simple reminder (placeholder)"""
        message = params.get('message', '')
        duration = params.get('duration_minutes', 5)
        
        # In a real implementation, you'd store this in a job queue
        return f"Reminder set: '{message}' in {duration} minutes"


class ConversationOrchestrator:
    """Main orchestrator for conversation flow with tools"""
    
    def __init__(self, db: Session):
        self.conversation_manager = ConversationManager(db)
        self.tool_system = ToolSystem(db)
        
    async def initialize(self):
        """Initialize tools and system"""
        # Register built-in tools
        await self.tool_system.register_tool(
            "get_current_time", 
            "Current Time", 
            "Get the current date and time",
            "utility",
            {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "Timezone (default: UTC)"}
                }
            },
            BasicTools.get_current_time
        )
        
        await self.tool_system.register_tool(
            "simple_calculator",
            "Calculator", 
            "Perform basic mathematical calculations",
            "utility",
            {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Mathematical expression"}
                },
                "required": ["expression"]
            },
            BasicTools.simple_calculator
        )
        
        await self.tool_system.register_tool(
            "set_reminder",
            "Set Reminder",
            "Set a simple reminder", 
            "productivity",
            {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Reminder message"},
                    "duration_minutes": {"type": "integer", "description": "Minutes from now"}
                },
                "required": ["message", "duration_minutes"]
            },
            BasicTools.set_reminder
        )
        
        logger.info("Conversation orchestrator initialized with basic tools")
    
    async def process_user_message(
        self, 
        user: User, 
        user_message: str,
        audio_metadata: Dict = None
    ) -> Tuple[str, Dict]:
        """Process user message and return AI response with metadata"""
        
        start_time = datetime.now()
        
        # Get or create conversation
        conversation = await self.conversation_manager.get_or_create_conversation(user)
        
        # Add user message
        user_msg = await self.conversation_manager.add_message(
            conversation, user, "user", user_message, audio_metadata
        )
        
        # Get conversation context
        context = await self.conversation_manager.get_conversation_context(conversation)
        
        # Check if user is asking for tool usage
        ai_response, tool_used = await self._generate_ai_response_with_tools(
            user_message, context, conversation, user
        )
        
        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Add AI response
        ai_msg = await self.conversation_manager.add_message(
            conversation, user, "assistant", ai_response, 
            processing_time=processing_time, model_used="gemini-1.5-flash"
        )
        
        return ai_response, {
            "conversation_id": str(conversation.id),
            "message_id": str(ai_msg.id),
            "processing_time": processing_time,
            "tool_used": tool_used,
            "context_length": len(context)
        }
    
    async def _generate_ai_response_with_tools(
        self, user_message: str, context: List[Dict], conversation: Conversation, user: User
    ) -> Tuple[str, bool]:
        """Generate AI response with potential tool usage"""
        
        # Get available tools
        tools = await self.tool_system.get_available_tools()
        
        # Create tool descriptions for AI
        tool_descriptions = []
        for tool in tools:
            tool_descriptions.append({
                "name": tool.name,
                "description": tool.description,
                "schema": tool.schema
            })
        
        # Simple tool detection (in a real implementation, you'd use function calling)
        tool_used = False
        
        # Basic tool trigger detection
        if "what time" in user_message.lower() or "current time" in user_message.lower():
            success, result, error = await self.tool_system.execute_tool("get_current_time", {})
            if success:
                tool_used = True
                return result, tool_used
        
        elif any(op in user_message.lower() for op in ["calculate", "math", "+", "-", "*", "/"]):
            # Extract calculation from message (simple approach)
            import re
            math_pattern = r'[\d\+\-\*/\(\)\.\s]+'
            match = re.search(math_pattern, user_message)
            if match:
                expression = match.group().strip()
                success, result, error = await self.tool_system.execute_tool(
                    "simple_calculator", {"expression": expression}
                )
                if success:
                    tool_used = True
                    return result, tool_used
        
        elif "remind me" in user_message.lower() or "set reminder" in user_message.lower():
            # Simple reminder parsing (you'd want more sophisticated parsing)
            success, result, error = await self.tool_system.execute_tool(
                "set_reminder", {"message": user_message, "duration_minutes": 5}
            )
            if success:
                tool_used = True
                return result, tool_used
        
        # If no tool used, generate regular AI response
        # This would integrate with your existing Gemini AI generation
        ai_response = f"I understand you said: '{user_message}'. I'm here to help you manage your life and house. You can ask me for the current time, calculations, or to set reminders!"
        
        return ai_response, tool_used