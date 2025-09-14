from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from google.cloud import texttospeech
from google.oauth2 import service_account
import io, os, json
import time
import urllib.parse

from authz import get_current_user  # Firebase auth for client requests
from shared.auth_service import require_service_auth  # Service-to-service auth

APP_TITLE = "june-tts"
app = FastAPI(title=APP_TITLE)

_tts_client = None

def build_tts_client():
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return texttospeech.TextToSpeechClient()

    sa_path = os.getenv("GCP_SA_PATH")
    if sa_path and os.path.exists(sa_path):
        creds = service_account.Credentials.from_service_account_file(sa_path)
        return texttospeech.TextToSpeechClient(credentials=creds)

    sa_json = os.getenv("GCP_SA_JSON")
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info)
        return texttospeech.TextToSpeechClient(credentials=creds)

    return texttospeech.TextToSpeechClient()

def get_client():
    global _tts_client
    if _tts_client is None:
        _tts_client = build_tts_client()
    return _tts_client

# -----------------------------------------------------------------------------
# Service-to-Service TTS Endpoint (FIXED)
# Protected by service authentication
# -----------------------------------------------------------------------------
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    language_code: str = Query("en-US"),
    voice_name: str = Query("en-US-Wavenet-D"),
    audio_encoding: str = Query("MP3"),  # MP3 | LINEAR16 | OGG_OPUS
    service_auth_data: dict = Depends(require_service_auth)  # Service auth
):
    """
    TTS endpoint for service-to-service communication
    Protected by service authentication
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Validate input length
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        # URL decode the text if needed
        decoded_text = urllib.parse.unquote(text)
        
        logger = logging.getLogger("uvicorn.error")
        logger.info(f"TTS request from {calling_service}: '{decoded_text[:100]}...' ({len(decoded_text)} chars)")
        
        client = get_client()
        synthesis_input = texttospeech.SynthesisInput(text=decoded_text)

        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )

        # Coerce encoding symbol safely
        encoding_symbol = getattr(texttospeech.AudioEncoding, audio_encoding.upper(), texttospeech.AudioEncoding.MP3)

        audio_config = texttospeech.AudioConfig(audio_encoding=encoding_symbol)

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        audio_bytes = response.audio_content
        
        # Determine media type for response
        enc_upper = audio_encoding.upper()
        if enc_upper == "MP3":
            media_type = "audio/mpeg"
            ext = "mp3"
        elif enc_upper == "OGG_OPUS":
            media_type = "audio/ogg"
            ext = "ogg"
        else:  # LINEAR16 and others treated as WAV container
            media_type = "audio/wav"
            ext = "wav"

        filename = f"speech.{ext}"
        
        logger.info(f"✅ TTS successful: {len(audio_bytes)} bytes generated")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Processed-By": "june-tts",
                "X-Caller-Service": calling_service
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Keep all your other existing endpoints...
@app.get("/healthz") 
async def healthz():
    return {
        "ok": True, 
        "service": "june-tts", 
        "timestamp": time.time(),
        "status": "healthy"
    }

@app.get("/")
async def root():
    return {"service": "june-tts", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080)