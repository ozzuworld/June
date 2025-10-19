from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from livekit import api
from .config import config

router = APIRouter(prefix="/api/livekit", tags=["livekit"])

class TokenRequest(BaseModel):
    service_identity: str

@router.post("/token")
async def get_service_token(req: TokenRequest):
    try:
        token = api.AccessToken(
            api_key=config.livekit.api_key,
            api_secret=config.livekit.api_secret,
        )
        identity = req.service_identity
        token.with_identity(identity)
        token.with_name(identity)
        # Grants: STT subscribes only, TTS publishes only
        grants = api.VideoGrants(
            room_join=True,
            room="ozzu-main",
            can_subscribe=identity == "june-stt",
            can_publish=identity == "june-tts",
            can_publish_data=True,
        )
        token.with_grants(grants)
        return {"token": token.to_jwt(), "ws_url": config.livekit.ws_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
