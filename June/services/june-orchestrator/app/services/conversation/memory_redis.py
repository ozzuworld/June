import json
import time
from typing import Optional
import redis.asyncio as redis

from .models import SessionHistory, Message

class ConversationMemoryService:
    def __init__(self, host: str, port: int = 6379, db: int = 1, password: Optional[str] = None, ttl_seconds: int = 86400):
        self._r = redis.Redis(host=host, port=port, db=db, password=password, encoding="utf-8", decode_responses=True)
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"june:session:{session_id}:history"

    async def get_history(self, session_id: str) -> SessionHistory:
        key = self._key(session_id)
        data = await self._r.get(key)
        if not data:
            return SessionHistory(session_id=session_id, messages=[])
        return SessionHistory.from_dict(json.loads(data))

    async def append(self, session_id: str, role: str, content: str, max_history: int = 20):
        hist = await self.get_history(session_id)
        hist.max_history = max_history
        hist.add(Message(role=role, content=content, timestamp=time.time()))
        await self._r.set(self._key(session_id), json.dumps(hist.to_dict()), ex=self._ttl)

    async def clear(self, session_id: str):
        await self._r.delete(self._key(session_id))
