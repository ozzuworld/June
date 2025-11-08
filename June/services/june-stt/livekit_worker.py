import os
import asyncio
import logging
from typing import Optional

import numpy as np
import httpx
from livekit import rtc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token + connection
# ---------------------------------------------------------------------------

async def get_livekit_token(
    identity: str,
    room_name: str = "ozzu-main",
    max_retries: int = 3,
) -> tuple[str, str]:
    """
    Get LiveKit token from orchestrator.

    Uses ORCHESTRATOR_URL if set, otherwise falls back to cluster default.
    Expects /token to return JSON with { token, livekitUrl/ws_url }.
    """
    base = os.getenv(
        "ORCHESTRATOR_URL",
        "https://api.ozzu.world",
    )

    paths = ["/token"]
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        for path in paths:
            url = f"{base}{path}"
            try:
                timeout = 5.0 + (attempt * 2.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.info(
                        f"Getting LiveKit token from {url} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    payload = {"roomName": room_name, "participantName": identity}
                    r = await client.post(url, json=payload)
                    r.raise_for_status()
                    data = r.json()

                    ws_url = data.get("livekitUrl") or data.get("ws_url")
                    token = data["token"]

                    if not ws_url:
                        raise RuntimeError(
                            f"Orchestrator response missing livekitUrl/ws_url: {data}"
                        )

                    logger.info("LiveKit token received")
                    return ws_url, token
            except Exception as e:
                last_err = e
                logger.warning(f"Token request failed at {url}: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(2.0 * (attempt + 1))

    raise RuntimeError(
        f"Failed to get LiveKit token after {max_retries} attempts: {last_err}"
    )


async def connect_room_as_subscriber(
    room: rtc.Room,
    identity: str,
    room_name: str = "ozzu-main",
    max_retries: int = 3,
) -> None:
    """
    Connect to LiveKit room with retry logic.
    Mirrors the pattern you had working.
    """
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            logger.info(
                f"Connecting to LiveKit as {identity} "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            ws_url, token = await get_livekit_token(
                identity,
                room_name=room_name,
                max_retries=2,
            )
            await room.connect(ws_url, token)
            logger.info(f"Connected to LiveKit room as {identity}")
            return
        except Exception as e:
            last_err = e
            logger.error(
                f"LiveKit connection error (attempt {attempt + 1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(3.0 * (attempt + 1))
            else:
                break

    raise RuntimeError(
        f"Failed to connect to LiveKit room after {max_retries} attempts: {last_err}"
    )


# ---------------------------------------------------------------------------
# Orchestrator Integration
# ---------------------------------------------------------------------------

async def send_to_orchestrator(
    room_name: str,
    participant: str,
    text: str,
    is_partial: bool = False
) -> bool:
    """
    Send transcription to orchestrator webhook
    """
    try:
        orchestrator_url = os.getenv(
            "ORCHESTRATOR_URL",
            "http://june-orchestrator.june-services.svc.cluster.local:8080"
        )
        
        webhook_url = f"{orchestrator_url}/api/webhooks/stt"
        
        # Build payload matching orchestrator's STTWebhookPayload model
        payload = {
            "event": "partial" if is_partial else "final",
            "room_name": room_name,
            "participant": participant,
            "text": text,
            "language": "en",
            "confidence": 1.0,
            "timestamp": "",
            "partial": is_partial,
            "segments": []
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Orchestrator webhook error: {response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"Failed to send to orchestrator: {e}")
        return False


# ---------------------------------------------------------------------------
# Audio → ASR
# ---------------------------------------------------------------------------

async def _handle_audio_track(asr_service, track: rtc.Track, participant: rtc.RemoteParticipant):
    """
    Subscribe to an audio track, feed PCM into WhisperStreaming processor and log transcripts.
    One processor per audio track.
    """
    from livekit.rtc import AudioStream

    logger.info(
        "Starting ASR stream for participant=%s, track=%s",
        participant.identity,
        track.sid,
    )

    processor = asr_service.create_processor()
    audio_stream = AudioStream(track)
    
    # Buffer to accumulate audio before processing
    audio_buffer = np.array([], dtype=np.float32)
    min_buffer_samples = int(16000 * 0.5)  # 500ms buffer before processing
    
    # Track room name for orchestrator
    room_name = os.getenv("LIVEKIT_ROOM", "ozzu-main")

    try:
        async for ev in audio_stream:
            frame = ev.frame
            # Convert memoryview to numpy array (per LiveKit docs)
            pcm = np.frombuffer(frame.data, dtype=np.int16)
            sr = frame.sample_rate

            # Downsample to 16k if needed
            if sr != 16000:
                factor = sr // 16000
                if factor <= 0:
                    continue
                pcm = pcm[::factor]

            # Convert to float32 in [-1, 1]
            audio = pcm.astype(np.float32) / 32768.0

            # Accumulate audio in buffer
            audio_buffer = np.append(audio_buffer, audio)

            # Process when we have enough audio (500ms)
            if len(audio_buffer) >= min_buffer_samples:
                # Insert the accumulated audio
                processor.insert_audio_chunk(audio_buffer)
                audio_buffer = np.array([], dtype=np.float32)  # Clear buffer
                
                # Check for transcription output
                output = processor.process_iter()
                if output[0] is not None:
                    beg, end, text = output
                    
                    # Log locally
                    logger.info(
                        "[LiveKit partial] %s %.2f–%.2fs: %s",
                        participant.identity,
                        beg,
                        end,
                        text,
                    )
                    
                    # Send to orchestrator (don't send partials to avoid overwhelming it)
                    # Only send when we have a meaningful chunk
                    if len(text.strip()) > 5:
                        asyncio.create_task(
                            send_to_orchestrator(
                                room_name=room_name,
                                participant=participant.identity,
                                text=text,
                                is_partial=True
                            )
                        )

        # Process any remaining audio in buffer
        if len(audio_buffer) > 0:
            processor.insert_audio_chunk(audio_buffer)
            
        # Flush final text when track ends
        output = processor.finish()
        if output[0] is not None:
            beg, end, text = output
            
            logger.info(
                "[LiveKit final] %s %.2f–%.2fs: %s",
                participant.identity,
                beg,
                end,
                text,
            )
            
            # Send final transcription to orchestrator
            if len(text.strip()) > 0:
                await send_to_orchestrator(
                    room_name=room_name,
                    participant=participant.identity,
                    text=text,
                    is_partial=False
                )
                
    except Exception as e:
        logger.error("Error in LiveKit audio handler: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def run_livekit_worker(asr_service):
    """
    Started once from FastAPI startup.

    - Connects to LiveKit as a subscriber
    - Listens for remote audio tracks
    - For each audio track, spawns _handle_audio_track.
    """
    identity = os.getenv("LIVEKIT_IDENTITY", "june-stt")
    room_name = os.getenv("LIVEKIT_ROOM", "ozzu-main")

    room = rtc.Room()

    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        from livekit.rtc import TrackKind

        if track.kind == TrackKind.KIND_AUDIO:
            logger.info(
                "Audio track subscribed from %s (sid=%s)",
                participant.identity,
                track.sid,
            )
            asyncio.create_task(_handle_audio_track(asr_service, track, participant))

    try:
        await connect_room_as_subscriber(
            room,
            identity=identity,
            room_name=room_name,
        )
        logger.info("LiveKit worker connected; waiting for audio tracks...")
        
        # Check orchestrator health
        try:
            orchestrator_url = os.getenv(
                "ORCHESTRATOR_URL",
                "https://api.ozzuw.world"
            )
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{orchestrator_url}/healthz")
                if response.status_code == 200:
                    logger.info("✅ Orchestrator is reachable")
                else:
                    logger.warning(f"⚠️ Orchestrator health check returned {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Could not reach orchestrator: {e}")
        
        # Keep alive; LiveKit manages its own reconnects internally
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error("LiveKit worker failed to connect: %s", e, exc_info=True)