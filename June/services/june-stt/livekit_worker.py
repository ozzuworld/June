import os
import asyncio
import logging
from typing import Optional

import numpy as np
import httpx
from livekit import rtc

logger = logging.getLogger(__name__)


async def get_livekit_token(identity: str, room_name: str = "ozzu-main", max_retries: int = 3) -> tuple[str, str]:
    base = os.getenv("ORCHESTRATOR_URL", "http://api.ozzu.world")
    paths = ["/token"]

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        for path in paths:
            url = f"{base}{path}"
            try:
                timeout = 5.0 + (attempt * 2.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.info(f"Getting LiveKit token from {url} (attempt {attempt + 1}/{max_retries})")
                    payload = {"roomName": room_name, "participantName": identity}
                    r = await client.post(url, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    ws_url = data.get("livekitUrl") or data.get("ws_url")
                    token = data["token"]
                    if not ws_url:
                        raise RuntimeError("Orchestrator response missing livekitUrl/ws_url")
                    logger.info("LiveKit token received")
                    return ws_url, token
            except Exception as e:
                last_err = e
                logger.warning(f"Token request failed at {url}: {e}")
        if attempt < max_retries - 1:
            await asyncio.sleep(2.0 * (attempt + 1))

    raise RuntimeError(f"Failed to get LiveKit token after {max_retries} attempts: {last_err}")


async def connect_room_as_subscriber(room: rtc.Room, identity: str, room_name: str = "ozzu-main", max_retries: int = 3) -> None:
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to LiveKit as {identity} (attempt {attempt + 1}/{max_retries})")
            ws_url, token = await get_livekit_token(identity, room_name=room_name, max_retries=2)
            await room.connect(ws_url, token)
            logger.info(f"Connected to LiveKit room as {identity}")
            return
        except Exception as e:
            last_err = e
            logger.error(f"LiveKit connection error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3.0 * (attempt + 1))
            else:
                break

    raise RuntimeError(f"Failed to connect to LiveKit room after {max_retries} attempts: {last_err}")


async def _handle_audio_track(asr_service, track: rtc.Track, participant: rtc.RemoteParticipant):
    from livekit.rtc import AudioStream  # lazy import

    logger.info(f"Starting ASR stream for participant={participant.identity}, track={track.sid}")

    processor = asr_service.create_processor()
    audio_stream = AudioStream(track)

    try:
        async for ev in audio_stream:
            frame = ev.frame
            pcm = frame.data  # int16 numpy array

            if frame.sample_rate != 16000:
                factor = frame.sample_rate // 16000
                if factor <= 0:
                    continue
                pcm = pcm[::factor]

            audio = pcm.astype(np.float32) / 32768.0

            processor.insert_audio_chunk(audio)

            for output in processor.process_iter():
                if output[0] is not None:
                    _, _, text = output
                    logger.info(f"[LiveKit partial] {participant.identity}: {text}")

        output = processor.finish()
        if output[0] is not None:
            _, _, text = output
            logger.info(f"[LiveKit final] {participant.identity}: {text}")
    except Exception as e:
        logger.error(f"Error in LiveKit audio handler: {e}")


async def run_livekit_worker(asr_service):
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
            logger.info(f"Audio track subscribed from {participant.identity}, starting ASR task")
            asyncio.create_task(_handle_audio_track(asr_service, track, participant))

    while True:
        try:
            await connect_room_as_subscriber(room, identity=identity, room_name=room_name)
            await room.wait_closed()
        except Exception as e:
            logger.error(f"LiveKit worker loop error: {e}")
            await asyncio.sleep(5.0)
