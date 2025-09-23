# app_tts_patch.py - Patch to update app.py for external TTS
# Add this to your app.py imports:

from external_tts_client import ExternalTTSClient

# Replace the TTS client initialization in startup_event():

# OLD: 
# tts_client = ChatterboxTTSClient(TTS_SERVICE_URL, service_auth)

# NEW:
# External TTS configuration
EXTERNAL_TTS_URL = os.getenv("EXTERNAL_TTS_URL", "")
if EXTERNAL_TTS_URL:
    tts_client = ExternalTTSClient(EXTERNAL_TTS_URL, service_auth)
    logger.info(f"✅ External TTS client configured: {EXTERNAL_TTS_URL}")
else:
    tts_client = None
    logger.warning("⚠️ EXTERNAL_TTS_URL not set - TTS disabled")

# Update the process_audio endpoint to handle external TTS:
# Replace the TTS synthesis call with:

if tts_client and reply:
    try:
        logger.info(f"🎵 Generating speech via external TTS: '{reply[:50]}...'")
        
        # Call external TTS service
        audio_response = await tts_client.synthesize_speech(
            text=reply,
            voice="default",  # Use your OpenVoice voice names
            speed=1.0,
            language="EN"
        )
        
        if audio_response:
            # Encode audio to base64 for response
            audio_b64 = base64.b64encode(audio_response).decode('utf-8')
            logger.info(f"✅ External TTS success: {len(audio_response)} bytes")
            
            tts_metadata = {
                "voice": "openvoice",
                "engine": "external-openvoice",
                "service": "external"
            }
        else:
            logger.error("❌ External TTS returned empty audio")
            
    except Exception as tts_error:
        logger.error(f"❌ External TTS failed: {tts_error}")
