"""
LiveKit Worker with STT Integration (OPTIMIZED)

KEY IMPROVEMENTS:
1. ✅ Proper segment concatenation (different time ranges)
2. ✅ Segment refinement detection (same time range)
3. ✅ 3-second cooldown after FINAL to prevent late partials
4. ✅ Duplicate partial deduplication
5. ✅ Better logging with timestamps
"""
import os
import asyncio
import logging
import time
from typing import Optional
from datetime import datetime

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
            "https://api.ozzu.world"
        )
        
        webhook_url = f"{orchestrator_url}/api/webhooks/stt"
        
        # Simple language detection based on character ranges
        def detect_language(text: str) -> str:
            """Basic language detection"""
            # Check for Chinese characters
            if any('\u4e00' <= char <= '\u9fff' for char in text):
                return "zh"
            # Check for Japanese characters
            elif any('\u3040' <= char <= '\u309f' for char in text) or any('\u30a0' <= char <= '\u30ff' for char in text):
                return "jp"
            # Check for Korean characters  
            elif any('\uac00' <= char <= '\ud7af' for char in text):
                return "ko"
            # Default to English
            return "en"
        
        detected_lang = detect_language(text)
        
        # Build payload matching orchestrator's STTWebhookPayload model
        payload = {
            "event": "partial" if is_partial else "final",
            "room_name": room_name,
            "participant": participant,
            "text": text,
            "language": detected_lang,
            "confidence": 1.0,
            "timestamp": datetime.utcnow().isoformat(),
            "partial": is_partial,
            "segments": []
        }
        
        # Only log finals and long partials to reduce noise
        if not is_partial or len(text) > 20:
            logger.info(
                f"📤 Sending to orchestrator: text='{text[:50]}...', "
                f"partial={is_partial}, len={len(text)}"
            )
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                if not is_partial:
                    logger.info(f"✅ Orchestrator accepted FINAL transcription")
                return True
            else:
                logger.error(
                    f"❌ Orchestrator webhook error: {response.status_code} - {response.text}"
                )
                return False
                
    except Exception as e:
        logger.error(f"❌ Failed to send to orchestrator: {e}")
        return False


# ---------------------------------------------------------------------------
# Audio → ASR with PROPER SEGMENT CONCATENATION + COOLDOWN
# ---------------------------------------------------------------------------

async def _handle_audio_track(asr_service, track: rtc.Track, participant: rtc.RemoteParticipant):
    """
    Subscribe to an audio track, feed PCM into WhisperStreaming processor and log transcripts.
    One processor per audio track.
    
    ✅ FIXED: Properly concatenates sequential segments (different time ranges)
    ✅ FIXED: Replaces text when same segment is being refined (same time range)
    ✅ OPTIMIZED: 3-second cooldown after FINAL to prevent stray partials
    ✅ OPTIMIZED: Deduplicates identical partials
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
    
    # Track accumulated text AND segment timing
    accumulated_text = ""  # Full utterance text built from segments
    last_segment_end = 0.0  # End time of last segment
    last_sent_partial = ""  # Last partial we sent (to avoid duplicates)
    
    # Track silence for finalizing utterances
    silence_counter = 0
    silence_threshold = 5  # Number of silent chunks before finalizing (500ms * 5 = 2.5s)

    # ✅ NEW: Cooldown tracking
    last_final_time = 0.0
    FINAL_COOLDOWN_SECONDS = 3.0  # Ignore partials for 3s after FINAL
    last_partial_text = ""  # For deduplication

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
                current_time = time.time()
                
                if output[0] is not None:
                    beg, end, text = output
                    text = text.strip()
                    
                    # Skip if empty
                    if not text:
                        continue
                    
                    # ✅ NEW: Check cooldown period after FINAL
                    time_since_final = current_time - last_final_time
                    if time_since_final < FINAL_COOLDOWN_SECONDS:
                        logger.debug(
                            f"⏸️ In cooldown ({time_since_final:.1f}s < {FINAL_COOLDOWN_SECONDS}s), "
                            f"ignoring partial: '{text[:30]}...'"
                        )
                        continue
                    
                    # ✅ NEW: Deduplicate identical partials
                    if text == last_partial_text:
                        logger.debug(f"⏸️ Duplicate partial ignored: '{text[:30]}...'")
                        continue
                    last_partial_text = text
                    
                    # Determine if this is a NEW segment or refinement
                    # NEW segment: beg is at or after the last segment's end
                    # Refinement: beg is before the last segment's end (overlapping/updating)
                    
                    is_new_segment = beg >= (last_segment_end - 0.3)  # Allow 0.3s overlap tolerance
                    
                    if is_new_segment:
                        # This is a NEW segment - CONCATENATE it
                        if accumulated_text:
                            # Add space before concatenating
                            accumulated_text = accumulated_text + " " + text
                            logger.debug(
                                f"[Concatenate] Adding segment: '{text}' → Full: '{accumulated_text[:50]}...'"
                            )
                        else:
                            # First segment
                            accumulated_text = text
                        
                        # Update the last segment end time
                        last_segment_end = end
                    else:
                        # This is a REFINEMENT of existing segment - REPLACE
                        accumulated_text = text
                        last_segment_end = end
                        logger.debug(
                            f"[Refinement] Replacing with: '{text}'"
                        )
                    
                    # Reset silence counter when we get new text
                    silence_counter = 0
                    
                    # Only send partial if it's significantly different from last one
                    if accumulated_text != last_sent_partial and len(accumulated_text) > len(last_sent_partial):
                        last_sent_partial = accumulated_text
                        
                        # Log locally
                        logger.info(
                            "[LiveKit partial] %s %.2f–%.2fs: %s",
                            participant.identity,
                            beg,
                            end,
                            accumulated_text,
                        )
                        
                        # Send partial transcription
                        asyncio.create_task(
                            send_to_orchestrator(
                                room_name=room_name,
                                participant=participant.identity,
                                text=accumulated_text,
                                is_partial=True
                            )
                        )
                else:
                    # No output means silence detected by VAD
                    silence_counter += 1
                    
                    # After enough silence, finalize with FULL accumulated text
                    if silence_counter >= silence_threshold and accumulated_text:
                        logger.info(
                            "[LiveKit FINAL after silence] %s: %s",
                            participant.identity,
                            accumulated_text,
                        )
                        
                        # Send FINAL transcription with complete accumulated text
                        await send_to_orchestrator(
                            room_name=room_name,
                            participant=participant.identity,
                            text=accumulated_text,
                            is_partial=False
                        )
                        
                        # ✅ NEW: Set cooldown timestamp
                        last_final_time = time.time()
                        
                        # Reset state for next utterance
                        accumulated_text = ""
                        last_segment_end = 0.0
                        last_sent_partial = ""
                        last_partial_text = ""  # ← Reset dedup tracker
                        silence_counter = 0

        # Process any remaining audio in buffer
        if len(audio_buffer) > 0:
            processor.insert_audio_chunk(audio_buffer)
            
        # CRITICAL: Flush final text when track ends
        output = processor.finish()
        if output[0] is not None:
            beg, end, text = output
            text = text.strip()
            
            if text:
                # Check if this is a new segment to concatenate
                if beg >= (last_segment_end - 0.3) and accumulated_text:
                    accumulated_text = accumulated_text + " " + text
                else:
                    accumulated_text = text
                    
                logger.info(
                    "[LiveKit FINAL on track end] %s %.2f–%.2fs: %s",
                    participant.identity,
                    beg,
                    end,
                    accumulated_text,
                )
                
                await send_to_orchestrator(
                    room_name=room_name,
                    participant=participant.identity,
                    text=accumulated_text,
                    is_partial=False
                )
                
                # ✅ Set final cooldown
                last_final_time = time.time()
        else:
            # Even if finish() returns None, send accumulated text if we have it
            if accumulated_text:
                logger.info(
                    "[LiveKit FINAL from accumulated on track end] %s: %s",
                    participant.identity,
                    accumulated_text,
                )
                await send_to_orchestrator(
                    room_name=room_name,
                    participant=participant.identity,
                    text=accumulated_text,
                    is_partial=False
                )
                last_final_time = time.time()
                
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
            # FILTER OUT june-tts to prevent feedback loop
            if participant.identity == "june-tts":
                logger.info(
                    "Ignoring audio track from june-tts (sid=%s) to prevent feedback loop",
                    track.sid,
                )
                return
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
                "https://api.ozzu.world"
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