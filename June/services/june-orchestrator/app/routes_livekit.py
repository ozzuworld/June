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
        
        # Unified grants: allow publish/subscribe for services and frontend clients
        grants = api.VideoGrants(
            room_join=True,
            room="ozzu-main",
            can_subscribe=True,
            can_publish=True,
            can_publish_data=True,
        )
        
        token.with_grants(grants)
        return {"token": token.to_jwt(), "ws_url": config.livekit.ws_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
