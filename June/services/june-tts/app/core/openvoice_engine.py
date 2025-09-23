import asyncio
import base64
import os
import tempfile
from typing import Optional, Tuple

import httpx
import soundfile as sf
import numpy as np

# ---------- Limits / supported ----------
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}
_MAX_TEXT_LEN = 2000
_MAX_REF_BYTES = 20 * 1024 * 1024  # 20 MB

# ---------- Globals (memoized models) ----------
_MELO = None                   # type: ignore
_CONVERTER = None              # type: ignore
_SAMPLE_SPEAKER_ID = None      # type: ignore


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default or "")
    if not val:
        raise RuntimeError(f"{name} is required")
    return val


def _melo_language(language: str) -> str:
    lang_map = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JA", "ko": "KO"}
    return lang_map.get(language, os.getenv("MELO_LANGUAGE", "EN"))


def _ensure_checkpoints() -> Tuple[str, str]:
    root = _env("OPENVOICE_CHECKPOINTS_V2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "tone_color_converter")
    if not os.path.isdir(base_root):
        raise RuntimeError(f"Missing MeloTTS base_speakers at {base_root}")
    if not os.path.isdir(conv_root):
        raise RuntimeError(f"Missing tone_color_converter at {conv_root}")
    return base_root, conv_root


async def _download_reference(url: str) -> str:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        if len(r.content) > _MAX_REF_BYTES:
            raise ValueError("reference_url file too large")
        fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".bin")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(r.content)
        return path


async def _write_reference_b64(b64: str) -> str:
    raw = base64.b64decode(b64)
    if len(raw) > _MAX_REF_BYTES:
        raise ValueError("reference_b64 too large")
    fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".bin")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _load_models_once() -> None:
    """
    Memoize MeloTTS + ToneColorConverter in module globals.
    Called from app lifespan so we avoid per-request cold starts.
    """
    global _MELO, _CONVERTER, _SAMPLE_SPEAKER_ID

    if _MELO is not None and _CONVERTER is not None:
        return

    # Import here to fail fast with a clear message if deps are missing.
    try:
        from melo.api import TTS as MeloTTS          # type: ignore
        from openvoice import se_extractor           # noqa: F401  # only for runtime availability check
        from openvoice.api import ToneColorConverter # type: ignore
    except Exception as e:
        raise RuntimeError(
            "OpenVoice V2 runtime not installed. "
            "Install MeloTTS/OpenVoice and ensure checkpoints_v2 are present. "
            f"Import error: {e}"
        )

    _, conv_root = _ensure_checkpoints()

    # Language pack is chosen at synthesis time; MeloTTS can be initialized once.
    # Many Melo builds accept a language parameter; if so, we can default to EN.
    # We keep a single instance to avoid duplicating GPU RAM.
    _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))

    # Tone color converter (V2)
    _CONVERTER = ToneColorConverter(checkpoint=conv_root)

    # Optional: default speaker id (pack dependent)
    _SAMPLE_SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "EN-US")


def warmup_models() -> None:
    """
    Public: call during FastAPI lifespan to preload weights onto GPU.
    """
    _load_models_once()
    # Optional no-op forward pass can be added if desired; often not necessary.


async def synthesize_v2_to_wav_path(
    *,
    text: str,
    language: str,
    reference_b64: Optional[str],
    reference_url: Optional[str],
    speed: float,
    volume: float,
    pitch: float,
    metadata: dict,
) -> str:
    # ---- Guard clauses ----
    if not text:
        raise ValueError("text is required")
    if len(text) > _MAX_TEXT_LEN:
        raise ValueError("text too long")
    lang = language.lower()
    if lang not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"language must be one of {_SUPPORTED_LANGUAGES}")
    if speed <= 0:
        raise ValueError("speed must be > 0")

    # Ensure models are resident
    _load_models_once()
    assert _MELO is not None and _CONVERTER is not None

    # Resolve reference
    ref_path: Optional[str] = None
    if reference_b64:
        ref_path = await _write_reference_b64(reference_b64)
    elif reference_url:
        ref_path = await _download_reference(reference_url)
    if not ref_path:
        raise ValueError("reference audio not provided")

    # ---- Base TTS (Melo) ----
    melo_lang = _melo_language(lang)
    # Some Melo builds allow switching language dynamically:
    # If yours requires re-instantiation per language, you can extend memoization
    # to a dict keyed by language. For now we set speaker id pack-wise.
    spk = _SAMPLE_SPEAKER_ID or "EN-US"

    base_audio, sr = _MELO.tts_to_audio(  # type: ignore[attr-defined]
        text=text,
        speaker_id=spk,
        speed=speed,
        volume=volume,
        pitch=pitch,
        language=melo_lang if "language" in _MELO.tts_to_audio.__code__.co_varnames else None,  # type: ignore
    )

    # ---- Extract speaker embedding ----
    from openvoice import se_extractor  # late import to keep top clean
    src_se = se_extractor.get_se(ref_path)

    # ---- Tone color conversion ----
    converted_audio = _CONVERTER.convert(  # type: ignore[attr-defined]
        audio=base_audio.astype(np.float32),
        sample_rate=sr,
        src_se=src_se,
    )

    # ---- Write final WAV (16-bit PCM) ----
    fd, out_path = tempfile.mkstemp(prefix="june-tts-v2-", suffix=".wav")
    os.close(fd)
    sf.write(out_path, converted_audio, sr, subtype="PCM_16")

    # Cleanup reference file asynchronously
    async def _cleanup():
        try:
            if os.path.exists(ref_path):
                os.remove(ref_path)
        except Exception:
            pass

    asyncio.create_task(_cleanup())
    return out_path
