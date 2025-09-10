from fastapi import FastAPI, Query, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from google.cloud import texttospeech
from google.oauth2 import service_account
import io, os, json

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

@app.get("/healthz")
async def healthz():
    try:
        _ = get_client()
        return {"ok": True, "service": APP_TITLE}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# -----------------------------------------------------------------------------
# Service-to-Service TTS Endpoint (NEW)
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
    
    client = get_client()
    synthesis_input = texttospeech.SynthesisInput(text=text)

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
    
    # Log the service call
    import logging
    logger = logging.getLogger("uvicorn.error")
    logger.info(f"TTS request from service: {calling_service}, text length: {len(text)}")
    
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Processed-By": "june-tts",
            "X-Caller-Service": calling_service
        }
    )

# -----------------------------------------------------------------------------
# Client TTS Endpoint (EXISTING) 
# Protected by Firebase authentication for direct client requests
# -----------------------------------------------------------------------------
@app.post("/v1/tts-client")
async def synthesize_speech_client(
    text: str = Query(..., description="Text to synthesize"),
    language_code: str = Query("en-US"),
    voice_name: str = Query("en-US-Wavenet-D"),
    audio_encoding: str = Query("MP3"),  # MP3 | LINEAR16 | OGG_OPUS
    user=Depends(get_current_user),      # Firebase auth for clients
):
    """
    TTS endpoint for direct client requests
    Protected by Firebase authentication
    """
    client = get_client()
    synthesis_input = texttospeech.SynthesisInput(text=text)

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
    
    # Correct media types for common encodings
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
    
    # Log the client call
    import logging
    logger = logging.getLogger("uvicorn.error")
    logger.info(f"TTS request from client: {user.get('uid', 'unknown')}, text length: {len(text)}")
    
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# -----------------------------------------------------------------------------
# Test endpoint to verify service authentication
# -----------------------------------------------------------------------------
@app.get("/v1/test-auth")
async def test_auth(service_auth_data: dict = Depends(require_service_auth)):
    """Test endpoint to verify service authentication is working"""
    return {
        "message": "Service authentication successful",
        "caller": service_auth_data.get("client_id"),
        "scopes": service_auth_data.get("scopes", []),
        "service": "june-tts"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080)