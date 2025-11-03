from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Message:
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    timestamp: float

@dataclass
class SessionHistory:
    session_id: str
    messages: List[Message]
    max_history: int = 20

    def add(self, msg: Message):
        self.messages.append(msg)
        # Trim to max_history from the end
        if len(self.messages) > self.max_history:
            overflow = len(self.messages) - self.max_history
            self.messages = self.messages[overflow:]

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "messages": [m.__dict__ for m in self.messages],
            "max_history": self.max_history,
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionHistory":
        msgs = [Message(**m) for m in d.get("messages", [])]
        return SessionHistory(session_id=d.get("session_id", "unknown"), messages=msgs, max_history=d.get("max_history", 20))
