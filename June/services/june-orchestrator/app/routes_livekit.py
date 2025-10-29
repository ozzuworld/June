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
        
        # FIXED: Give both services full permissions for proper WebRTC connection
        grants = api.VideoGrants(
            room_join=True,
            room="ozzu-main",
            can_subscribe=True,  # ✅ Both services need this for WebRTC
            can_publish=True,    # ✅ Both services need this for WebRTC  
            can_publish_data=True,
        )
        
        # Alternatively, if you want to keep them separate:
        # grants = api.VideoGrants(
        #     room_join=True,
        #     room="ozzu-main",
        #     can_subscribe=True,                              # Both need subscribe for WebRTC
        #     can_publish=identity in ["june-tts", "june-stt"], # Only specific services publish
        #     can_publish_data=True,
        # )
        
        token.with_grants(grants)
        return {"token": token.to_jwt(), "ws_url": config.livekit.ws_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
