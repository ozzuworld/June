import asyncio
import base64
import glob
import os
import tempfile
from typing import Optional, Tuple, Callable, Dict, Any

import httpx
import numpy as np
import soundfile as sf

# -------- Limits / supported (env-overridable) --------
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))  # 20 MB default
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}

# -------- Memoized globals --------
_MELO = None                   # type: ignore
_CONVERTER = None              # type: ignore
_SPEAKER_ID = None             # type: ignore
_CONVERT_FN: Optional[Callable[..., np.ndarray]] = None  # selected convert function


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default or "")
    if not val:
        raise RuntimeError(f"{name} is required")
    return val


def _melo_language(language: str) -> str:
    # Map to Melo packs (common codes)
    lang_map = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JA", "ko": "KO"}
    return lang_map.get(language, os.getenv("MELO_LANGUAGE", "EN"))


def _ensure_checkpoints() -> Tuple[str, str, str]:
    """
    Returns (root, base_root, conv_root) and validates presence.
    """
    root = _env("OPENVOICE_CHECKPOINTS_V2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "tone_color_converter")
    if not os.path.isdir(base_root):
        raise RuntimeError(f"Missing MeloTTS base_speakers at {base_root}")
    if not os.path.isdir(conv_root):
        raise RuntimeError(f"Missing tone_color_converter at {conv_root}")
    return root, base_root, conv_root


def _find_converter_ckpt(conv_root: str) -> str:
    """
    Find a checkpoint file (*.pth or *.pt) in tone_color_converter/.
    """
    for pattern in ("*.pth", "**/*.pth", "*.pt", "**/*.pt"):
        matches = glob.glob(os.path.join(conv_root, pattern), recursive=True)
        if matches:
            return matches[0]
    raise RuntimeError(f"No converter checkpoint (*.pth|*.pt) found under {conv_root}")


async def _download_reference(url: str) -> str:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    timeout = httpx.Timeout(30.0)
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
    Version-agnostic loader for MeloTTS + ToneColorConverter.
    Handles different OpenVoice APIs (constructor args / load methods / convert methods).
    """
    global _MELO, _CONVERTER, _SPEAKER_ID, _CONVERT_FN
    if _MELO is not None and _CONVERTER is not None and _CONVERT_FN is not None:
        return

    try:
        from melo.api import TTS as MeloTTS          # type: ignore
        from openvoice.api import ToneColorConverter # type: ignore
        from openvoice import se_extractor           # noqa: F401
    except Exception as e:
        raise RuntimeError(
            "OpenVoice V2 runtime not installed. "
            "Install MeloTTS/OpenVoice and ensure checkpoints_v2 are present. "
            f"Import error: {e}"
        )

    _, _, conv_root = _ensure_checkpoints()
    ckpt = _find_converter_ckpt(conv_root)

    # ---- Initialize Melo once ----
    _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))
    _SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "EN-US")

    # ---- Initialize ToneColorConverter across API variants ----
    converter = None
    # Variant A: newer builds want config_path=..., then load_ckpt/checkpoint
    try:
        cfg_path = os.path.join(conv_root, "config.json")
        converter = ToneColorConverter(config_path=os.path.join(conv_root, 'config.json'), device=os.getenv('OPENVOICE_DEVICE', 'cuda' if os.getenv('CUDA_VISIBLE_DEVICES','')!='' else 'cpu'))  # type: ignore[call-arg]
        if hasattr(converter, "load_ckpt"):
            converter.load_ckpt(ckpt)
        elif hasattr(converter, "load"):
            converter.load(ckpt_path=ckpt)
    except TypeError:
        # Variant B: empty constructor + load()/load_ckpt()
        converter = ToneColorConverter(config_path=os.path.join(conv_root, 'config.json'), device=os.getenv('OPENVOICE_DEVICE', 'cuda' if os.getenv('CUDA_VISIBLE_DEVICES','')!='' else 'cpu'))
        if hasattr(converter, "load_ckpt"):
            converter.load_ckpt(ckpt)
        elif hasattr(converter, "load"):
            converter.load(ckpt_path=ckpt)
        else:
            raise RuntimeError("Unsupported ToneColorConverter: missing load/load_ckpt")

    # Pick a convert function that exists on this build
    if hasattr(converter, "convert"):
        def _do_convert(audio: np.ndarray, sample_rate: int, src_se: np.ndarray) -> np.ndarray:
            return converter.convert(audio=audio.astype(np.float32), sample_rate=sample_rate, src_se=src_se)
        _CONVERT_FN = _do_convert
    elif hasattr(converter, "tone_color_convert"):
        def _do_convert(audio: np.ndarray, sample_rate: int, src_se: np.ndarray) -> np.ndarray:
            return converter.tone_color_convert(audio.astype(np.float32), sample_rate, src_se)  # type: ignore[attr-defined]
        _CONVERT_FN = _do_convert
    else:
        raise RuntimeError("Unsupported ToneColorConverter: no convert/tone_color_convert method")

    _CONVERTER = converter


def warmup_models() -> None:
    """Load weights into memory at startup to avoid first-call cold start."""
    _load_models_once()
    # Optional: do a tiny no-op if needed by future builds.


def _maybe_add_language_kw(fn: Callable[..., Any], kwargs: Dict[str, Any], language: str) -> None:

def _filter_kwargs_for(fn, kwargs):
    \"\"\"Return a copy of kwargs containing only params accepted by fn.\"\"\"
    try:
        from inspect import signature, Parameter
        sig = signature(fn)
        out = {}
        for k, v in kwargs.items():
            if k in sig.parameters:
                out[k] = v
        # If fn has **kwargs, pass everything
        if any(p.kind == Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return kwargs
        return out
    except Exception:
        # if inspection fails, return conservative subset
        allow = {"text","speaker_id","speed","language","output_path"}
        return {k:v for k,v in kwargs.items() if k in allow}


    """Add language= to kwargs if target function accepts it."""
    try:
        from inspect import signature
        sig = signature(fn)
        if "language" in sig.parameters:
            kwargs["language"] = language
    except Exception:
        pass


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

    _load_models_once()
    assert _MELO is not None and _CONVERTER is not None and _CONVERT_FN is not None

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
    spk = _SPEAKER_ID or "EN-US"

    _tts_kwargs: Dict[str, Any] = dict(text=text, speaker_id=spk, speed=speed, volume=volume, pitch=pitch)

    base_audio: Optional[np.ndarray] = None
    sr: Optional[int] = None

    # Preferred: direct audio return
    if hasattr(_MELO, "tts_to_audio"):
        _maybe_add_language_kw(_MELO.tts_to_audio, _tts_kwargs, melo_lang)
        base_audio, sr = _MELO.tts_to_audio(**_filter_kwargs_for(_MELO.tts_to_audio, _tts_kwargs))  # type: ignore[attr-defined]

    # Fallback: file-based API
    elif hasattr(_MELO, "tts_to_file"):
        _maybe_add_language_kw(_MELO.tts_to_file, _tts_kwargs, melo_lang)
        fd, tmpwav = tempfile.mkstemp(prefix="melo-out-", suffix=".wav")
        os.close(fd)
        try:
            _MELO.tts_to_file(output_path=tmpwav, **_filter_kwargs_for(_MELO.tts_to_file, _tts_kwargs))  # type: ignore[attr-defined]
            data, sr = sf.read(tmpwav, dtype="float32")
            base_audio = data
        finally:
            try:
                os.remove(tmpwav)
            except Exception:
                pass

    # Legacy: tts() returns ndarray (infer or read sample rate)
    elif hasattr(_MELO, "tts"):
        _maybe_add_language_kw(_MELO.tts, _tts_kwargs, melo_lang)
        base_audio = _MELO.tts(**_filter_kwargs_for(_MELO.tts, _tts_kwargs))  # type: ignore[attr-defined]
        # discover a sample rate attribute, else default
        sr = getattr(_MELO, "sample_rate", None) or getattr(_MELO, "sr", None) or 22050

    else:
        raise RuntimeError("Unsupported MeloTTS build: no tts_to_audio/tts_to_file/tts")

    if base_audio is None or sr is None:
        raise RuntimeError("MeloTTS synthesis failed: no audio or sample rate")

    # ---- Speaker embedding from reference ----
    from openvoice import se_extractor
    try:
        src_se, _ = se_extractor.get_se(ref_path, converter, vad=True)
    except TypeError:
        src_se = se_extractor.get_se(ref_path)

    # ---- Tone color conversion ----
    converted_audio = _CONVERT_FN(base_audio, sr, src_se)  # np.ndarray float32

    # ---- Write WAV (16-bit PCM) ----
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
