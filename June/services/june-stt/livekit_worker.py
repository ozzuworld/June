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
# Audio → ASR
# ---------------------------------------------------------------------------

async def _handle_audio_track(asr_service, track: rtc.Track, participant: rtc.RemoteParticipant):
    """
    Subscribe to an audio track, feed PCM into WhisperStreaming processor and log transcripts.
    One processor per audio track.
    """
    from livekit.rtc import AudioStream  # lazy import to avoid hard dependency if unused

    logger.info(
        "Starting ASR stream for participant=%s, track=%s",
        participant.identity,
        track.sid,
    )

    processor = asr_service.create_processor()
    audio_stream = AudioStream(track)

    try:
        async for ev in audio_stream:
            frame = ev.frame
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

            processor.insert_audio_chunk(audio)

            for output in processor.process_iter():
                if output[0] is not None:
                    beg, end, text = output
                    logger.info(
                        "[LiveKit partial] %s %.2f–%.2fs: %s",
                        participant.identity,
                        beg,
                        end,
                        text,
                    )

        # flush final text when track ends
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
        # Keep alive; LiveKit manages its own reconnects internally
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error("LiveKit worker failed to connect: %s", e, exc_info=True)