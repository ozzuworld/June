# routers/conversation_routes.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

# Use your real dependencies (remove the stubs!)
from db.session import get_db
from clients.http import get_http_client

router = APIRouter(prefix="/v1", tags=["Conversation"])

# =========================== Pydantic Schemas ================================

class Message(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(..., description="Message role")
    type: Literal["text", "audio", "tool"] = "text"
    text: Optional[str] = None
    audio_url: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None

class ToolResult(BaseModel):
    name: str
    success: bool = True
    detail: Optional[str] = None
    output: Optional[Dict[str, Any]] = None

class ConversationInput(BaseModel):
    conversation_id: Optional[str] = Field(None, description="Client conversation id, if continuing")
    messages: List[Message] = Field(default_factory=list, description="Full or recent message window")
    text: Optional[str] = Field(None, description="Shortcut for a single user text message")
    stream: bool = Field(False, description="Whether the client expects streaming (SSE/WS handled elsewhere)")
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConversationOutput(BaseModel):
    ok: bool = True
    conversation_id: str
    message: Message
    used_tools: List[ToolResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class WhoAmI(BaseModel):
    ok: bool = True
    subject: Optional[str] = None
    token_present: bool = False

class Pong(BaseModel):
    ok: bool = True
    service: str = "june-orchestrator"
    status: str = "healthy"

# ============================= Helpers =======================================

def _extract_bearer_subject(authorization: Optional[str]) -> Optional[str]:
    """
    Very light parser; swap with real JWT verification later.
    Return some subject/username if token is present.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    # TODO: verify JWT and extract sub/claims
    return "user@token" if token else None

async def _orchestrate_chat(
    payload: ConversationInput,
    db: Any,
    http: Any,
    subject: Optional[str],
) -> ConversationOutput:
    """
    Main chat orchestration logic:
      1) Validate input
      2) (Optional) Persist to DB
      3) Call LLM/tools/TT(S) as needed via `http`
      4) Return normalized assistant message
    """
    warnings: List[str] = []
    used_tools: List[ToolResult] = []

    # Normalize input (accept either `text` or last user text message)
    user_text: Optional[str] = payload.text
    if not user_text:
        for m in reversed(payload.messages):
            if m.role == "user" and m.type == "text" and m.text:
                user_text = m.text
                break

    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user text provided (set `text` or include a user text message).",
        )

    # TODO: example tool call via `http` client
    # result = await http.get("http://knowledge/lookup", params={"q": user_text})
    # used_tools.append(ToolResult(name="knowledge_lookup", success=True, output=result.json()))

    # TODO: example LLM call; for now just echo
    assistant_reply = f"Echo: {user_text}"

    return ConversationOutput(
        ok=True,
        conversation_id=payload.conversation_id or f"conv_{uuid4().hex}",
        message=Message(role="assistant", type="text", text=assistant_reply),
        used_tools=used_tools,
        warnings=warnings,
    )

# ============================== Routes =======================================

@router.get("/ping", response_model=Pong, summary="Health probe for the /v1 scope")
async def ping() -> Pong:
    return Pong()

@router.get(
    "/whoami",
    response_model=WhoAmI,
    summary="Return token presence and a stubbed subject",
)
async def whoami(authorization: Optional[str] = Header(default=None)) -> WhoAmI:
    subject = _extract_bearer_subject(authorization)
    return WhoAmI(ok=True, subject=subject, token_present=authorization is not None)

@router.post("/chat", response_model=ConversationOutput, summary="Orchestrate a chat turn")
async def chat(
    payload: ConversationInput,
    request: Request,
    db: Any = Depends(get_db),
    http: Any = Depends(get_http_client),
    authorization: Optional[str] = Header(default=None),
) -> ConversationOutput:
    subject = _extract_bearer_subject(authorization)
    try:
        return await _orchestrate_chat(payload, db=db, http=http, subject=subject)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unhandled error: {e.__class__.__name__}",
        ) from e
