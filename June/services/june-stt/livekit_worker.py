# livekit_worker.py
import os
import asyncio
import logging
import io

import httpx
import numpy as np
import soundfile as soundfile
from livekit import rtc

logger = logging.getLogger(__name__)

ORCHESTRATOR_URL_DEFAULT = "http://june-orchestrator.june-services.svc.cluster.local:8080"
LIVEKIT_ROOM_DEFAULT = "ozzu-main"
IDENTITY_DEFAULT = "june-stt-asr"


async def get_livekit_token(identity: str, room_name: str) -> tuple[str, str]:
    """
    Ask the orchestrator for a LiveKit token.

    Expects ORCHESTRATOR_URL env var, or uses cluster default.
    POST {base}/token with JSON {roomName, participantName}
    Response must contain: token, and either livekitUrl or ws_url.
    """
    base = os.getenv("ORCHESTRATOR_URL", ORCHESTRATOR_URL_DEFAULT)
    url = f"{base}/token"

    payload = {"roomName": room_name, "participantName": identity}
    timeout = httpx.Timeout(10.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.info(f"[LiveKit] Requesting token from {url} for {identity} in room {room_name}")
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    ws_url = data.get("livekitUrl") or data.get("ws_url")
    if not ws_url:
        raise RuntimeError(f"No livekitUrl/ws_url in token response: {data}")

    token = data["token"]
    logger.info("[LiveKit] Got token")
    return ws_url, token


async def connect_room_as_subscriber(room: rtc.Room, identity: str, room_name: str) -> None:
    """Connect to LiveKit as a subscriber."""
    ws_url, token = await get_livekit_token(identity, room_name)
    logger.info(f"[LiveKit] Connecting to {ws_url} as {identity}")
    await room.connect(ws_url, token)
    logger.info("[LiveKit] Connected to room")


async def _handle_audio_track(track: rtc.Track, participant: rtc.Participant, asr_service) -> None:
    """
    Subscribe to an audio track and push PCM16 frames into OnlineASRProcessor.

    This directly uses asr_service.create_processor(), same as your WebSocket handler.
    """
    from livekit.rtc import AudioStream  # local import to avoid hard requirement if LiveKit unused

    logger.info(f"[LiveKit] Subscribed to audio track from {participant.identity}")

    # One ASR processor per audio stream (like one websocket session)
    processor = asr_service.create_processor()

    # LiveKit frames → 16 kHz, mono
    stream = AudioStream(track=track, sample_rate=16000, num_channels=1)

    try:
        async for frame in stream:
            # frame.data is int16 PCM
            raw_bytes = frame.data

            audio_buffer = io.BytesIO(raw_bytes)
            sf = soundfile.SoundFile(
                audio_buffer,
                channels=1,
                endian="LITTLE",
                samplerate=16000,
                subtype="PCM_16",
                format="RAW",
            )
            audio = sf.read(dtype=np.float32)

            # Feed into online ASR
            processor.insert_audio_chunk(audio)

            for output in processor.process_iter():
                if output[0] is None:
                    continue
                beg, end, text = output
                # For now we just log. You can later send this back via LiveKit data, HTTP, etc.
                logger.info(
                    f"[LiveKit][partial] {participant.identity} "
                    f"{beg:.2f}-{end:.2f}s: {text}"
                )

    except Exception as e:
        logger.error(f"[LiveKit] error while reading audio from {participant.identity}: {e}")
    finally:
        try:
            output = processor.finish()
            if output[0] is not None:
                beg, end, text = output
                logger.info(
                    f"[LiveKit][final] {participant.identity} "
                    f"{beg:.2f}-{end:.2f}s: {text}"
                )
        except Exception:
            pass

        logger.info(f"[LiveKit] Audio stream closed for {participant.identity}")


async def run_livekit_worker(asr_service) -> None:
    """
    Background task started from FastAPI startup.

    - Connects to LiveKit
    - Listens for audio tracks
    - For each audio track, starts a handler that feeds into the ASR processor.
    """
    identity = os.getenv("LIVEKIT_IDENTITY", IDENTITY_DEFAULT)
    room_name = os.getenv("LIVEKIT_ROOM", LIVEKIT_ROOM_DEFAULT)

    room = rtc.Room()

    @room.on("track_subscribed")
    def _on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.Participant,
        *_,
    ):
        from livekit.rtc import AudioTrack

        if not isinstance(track, AudioTrack):
            return

        logger.info(
            f"[LiveKit] Audio track subscribed from {participant.identity} "
            f"(sid={track.sid})"
        )
        asyncio.create_task(_handle_audio_track(track, participant, asr_service))

    @room.on("participant_disconnected")
    def _on_participant_disconnected(participant: rtc.Participant, *_):
        logger.info(f"[LiveKit] Participant disconnected: {participant.identity}")

    while True:
        try:
            await connect_room_as_subscriber(room, identity, room_name)
            # Keep the worker alive as long as the room is connected
            while room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(5.0)

            logger.warning("[LiveKit] Room disconnected, retrying in 3s...")
            await asyncio.sleep(3.0)

        except Exception as e:
            logger.error(f"[LiveKit] Fatal error in worker: {e}")
            # Backoff, but keep trying forever
            await asyncio.sleep(5.0)
