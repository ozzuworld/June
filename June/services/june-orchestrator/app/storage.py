"""
Thread-safe in-memory conversation storage
TODO: Replace with Redis for production
"""
import asyncio
from typing import Dict, List, Any
from datetime import datetime
from collections import defaultdict

# Conversation storage
_conversations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(user_id: str) -> asyncio.Lock:
    """Get or create lock for user"""
    if user_id not in _locks:
        _locks[user_id] = asyncio.Lock()
    return _locks[user_id]


async def add_message(user_id: str, role: str, text: str) -> None:
    """
    Add message to conversation (thread-safe)
    
    Args:
        user_id: User identifier
        role: Message role (user/assistant)
        text: Message content
    """
    lock = _get_lock(user_id)
    
    async with lock:
        message = {
            "role": role,
            "text": text,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        _conversations[user_id].append(message)
        
        # Keep only last 20 messages
        if len(_conversations[user_id]) > 20:
            _conversations[user_id] = _conversations[user_id][-20:]


async def get_conversation(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get conversation history (thread-safe)
    
    Args:
        user_id: User identifier
        limit: Maximum number of messages to return
        
    Returns:
        List of messages
    """
    lock = _get_lock(user_id)
    
    async with lock:
        messages = _conversations.get(user_id, [])
        return messages[-limit:] if len(messages) > limit else messages


async def clear_conversation(user_id: str) -> None:
    """Clear conversation history for user"""
    lock = _get_lock(user_id)
    
    async with lock:
        if user_id in _conversations:
            del _conversations[user_id]


def get_stats() -> Dict[str, Any]:
    """Get storage statistics"""
    return {
        "total_users": len(_conversations),
        "total_messages": sum(len(msgs) for msgs in _conversations.values()),
        "users_with_locks": len(_locks)
    }