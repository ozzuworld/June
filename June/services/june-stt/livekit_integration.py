import os
import asyncio
import logging
import httpx
import websockets

from livekit import rtc
from livekit.rtc import AudioStream  # async audio frames

try:
    # if you already have this config module, keep using it
    from config import config
except ImportError:
    config = type("Dummy", (), {})()  # fallback dummy


logger = logging.getLogger(__name__)


# ------------------------------
#  TOKEN + ROOM CONNECTION
# ------------------------------
async def get_livekit_token(
    identity: str,
    room_name: str = "ozzu-main",
    max_retries: int = 3,
) -> tuple[str, str]:
    """
    EXACTLY the same logic you showed, just copied here so this file is standalone.
    """
    base = os.getenv(
        "ORCHESTRATOR_URL",
        getattr(
            config,
            "ORCHESTRATOR_URL",
            "http://june-orchestrator.june-services.svc.cluster.local:8080",
        ),
    )

    paths = ["/token"]
    last_err = None

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
                    ws_url = (
                        data.get("livekitUrl")
                        or data.get("ws_url")
                        or getattr(config, "LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
                    )
                    token = data["token"]
                    logger.info("LiveKit token received")
                    return ws_url, token
            except Exception as e:
                last_err = e
                logger.warning(f"Token request failed at {url}: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(2.0 * (attempt + 1))

    raise RuntimeError(f"Failed to get LiveKit token after {max_retries} attempts: {last_err}")


async def connect_room_as_subscriber(
    room: rtc.Room,
    identity: str,
    room_name: str = "ozzu-main",
    max_retries: int = 3,
) -> None:
    """
    Same logic you pasted, kept intact.
    """
    for attempt in range(max_retries):
        try:
            logger.info(
                f"Connecting to LiveKit as {identity} "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            ws_url, token = await get_livekit_token(
                identity, room_name=room_name, max_retries=2
            )
            await room.connect(ws_url, token)  # default auto_subscribe=True
            logger.info(f"Connected to LiveKit room as {identity}")
            return
        except ConnectionError as e:
            logger.error(
                f"Connection error (attempt {attempt + 1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                wait_time = 3.0 * (attempt + 1)
                await asyncio.sleep(wait_time)
            else:
                raise
        except Exception as e:
            logger.error(f"LiveKit connection error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2.0)
            else:
                raise

    raise RuntimeError(f"Failed to connect to LiveKit room after {max_retries} attempts")


# ------------------------------
#  AUDIO → STT BRIDGE
# ------------------------------
async def pump_track_to_stt(track: rtc.Track, stt_ws: websockets.WebSocketClientProtocol):
    """
    Take a *remote audio* track from LiveKit and stream it into june-stt.

    - AudioStream will resample to 16 kHz, 1 channel (mono)
    - Data is int16 PCM (s16le), which is exactly what your /ws/transcribe expects.
    """
    logger.info("Starting AudioStream for track %s", getattr(track, "sid", "unknown"))
    audio_stream = AudioStream(
        track,
        sample_rate=16000,  # what faster-whisper is using
        num_channels=1,     # mono
    )

    try:
        async for event in audio_stream:
            frame = event.frame
            # frame.data is int16 memoryview; convert to raw bytes
            pcm_bytes = frame.data.tobytes()
            if not pcm_bytes:
                continue

            await stt_ws.send(pcm_bytes)
    except asyncio.CancelledError:
        logger.info("Audio pump task cancelled for track %s", getattr(track, "sid", "unknown"))
    except Exception as e:
        logger.error("Error in pump_track_to_stt: %s", e, exc_info=True)
    finally:
        await audio_stream.aclose()
        logger.info("AudioStream closed for track %s", getattr(track, "sid", "unknown"))


async def read_stt_results(stt_ws: websockets.WebSocketClientProtocol):
    """
    Read text/JSON messages coming back from june-stt and log them.
    Adapt this to forward to your app if you want.
    """
    try:
        async for message in stt_ws:
            # Whatever main.py sends back (likely JSON with 'text' / 'is_final')
            logger.info("STT RESULT: %s", message)
    except asyncio.CancelledError:
        logger.info("STT result reader cancelled")
    except Exception as e:
        logger.error("Error while reading STT results: %s", e, exc_info=True)


# ------------------------------
#  MAIN ENTRYPOINT
# ------------------------------
async def main():
    logging.basicConfig(level=logging.INFO)

    # Where your STT container is listening
    # You already ran it with: docker run --gpus all -p 8000:8000 ozzuworld/june-stt
    stt_ws_url = os.getenv("STT_WS_URL", "ws://localhost:8000/ws/transcribe")

    # LiveKit identity/room
    identity = os.getenv("LIVEKIT_IDENTITY", "june-stt-bridge")
    room_name = os.getenv("LIVEKIT_ROOM", "ozzu-main")

    logger.info("Connecting to STT websocket at %s", stt_ws_url)
    async with websockets.connect(stt_ws_url) as stt_ws:
        # Task that prints ASR results
        asyncio.create_task(read_stt_results(stt_ws))

        # Create LiveKit room + subscribe to tracks
        room = rtc.Room()

        @room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ):
            # Only care about audio
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info(
                    "Audio track subscribed: %s from participant %s",
                    publication.sid,
                    participant.identity,
                )
                asyncio.create_task(pump_track_to_stt(track, stt_ws))

        # Connect to room and start receiving media
        await connect_room_as_subscriber(
            room,
            identity=identity,
            room_name=room_name,
        )

        logger.info("Bridge running. Waiting for audio in room '%s'...", room_name)

        # Just keep this process alive.
        # CTRL+C to kill, or implement your own shutdown logic.
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await room.disconnect()
            logger.info("Disconnected from LiveKit room")


if __name__ == "__main__":
    asyncio.run(main())
