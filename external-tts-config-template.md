# External TTS Service Configuration

## Required: Configure your OpenVoice service to accept June IDP authentication

### 1. JWT Validation Setup

Your external TTS service must validate JWT tokens from the June IDP:

**Issuer**: `https://june-idp.allsafe.world/auth/realms/june`
**JWKS URL**: `https://june-idp.allsafe.world/auth/realms/june/protocol/openid-connect/certs`

### 2. Example JWT validation (Python/FastAPI)

```python
import jwt
import httpx
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer

security = HTTPBearer()

class JWTValidator:
    def __init__(self):
        self.issuer = "https://june-idp.allsafe.world/auth/realms/june"
        self.jwks_url = f"{self.issuer}/protocol/openid-connect/certs"
        self._jwks = None
    
    async def get_jwks(self):
        if not self._jwks:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url)
                self._jwks = response.json()
        return self._jwks
    
    async def validate_token(self, token: str):
        try:
            # Get public keys
            jwks = await self.get_jwks()
            
            # Decode header to get kid
            header = jwt.get_unverified_header(token)
            key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
            
            # Convert JWK to public key
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            
            # Validate token
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience="account"
            )
            
            return payload
            
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

# Usage in your TTS endpoints
validator = JWTValidator()

async def require_auth(credentials = Depends(security)):
    return await validator.validate_token(credentials.credentials)

@app.post("/v1/tts")
async def synthesize_speech(request: TTSRequest, auth = Depends(require_auth)):
    # Your TTS logic here
    pass
```

### 3. Expected API Endpoints

Your service should implement:

- `POST /v1/tts` - Text to speech synthesis
- `POST /v1/clone` - Voice cloning
- `GET /health` or `/healthz` - Health check
- `GET /v1/voices` - List available voices (optional)

### 4. Request/Response Format

**TTS Request**:
```json
{
  "text": "Hello world",
  "voice": "default",
  "speed": 1.0,
  "language": "EN",
  "format": "wav",
  "quality": "high"
}
```

**Response**: Raw audio bytes with proper Content-Type header

### 5. Security Checklist

- [ ] JWT token validation implemented
- [ ] HTTPS enabled with valid certificate
- [ ] Rate limiting configured
- [ ] Input validation (text length, audio size limits)
- [ ] Proper error handling and logging
- [ ] Health check endpoint available
