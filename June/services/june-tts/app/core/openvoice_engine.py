import asyncio
import base64
import glob
import inspect
import os
import tempfile
from typing import Optional, Tuple, Callable, Dict, Any

import httpx
import numpy as np
import soundfile as sf

# -------- NLTK bootstrap (quiet) --------
def _ensure_nltk() -> None:
    try:
        import nltk
        for res, kind in (("averaged_perceptron_tagger_eng", "taggers"), ("cmudict", "corpora")):
            try:
                sub = f"{kind}/{res}/" if kind == "taggers" else f"{kind}/{res}"
                nltk.data.find(sub)
            except LookupError:
                nltk.download(res, quiet=True, raise_on_error=True)
    except Exception:
        # If offline, Melo will raise a clearer error later
        pass

# -------- Limits / supported (env-overridable) --------
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))  # 20 MB
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}

# -------- Memoized globals --------
_MELO = None                   # type: ignore
_CONVERTER = None              # type: ignore
_SPEAKER_ID = None             # type: ignore
_CONVERT_FN: Optional[Callable[..., np.ndarray]] = None  # selected convert function

# -------- Utils --------
def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default or "")
    if not val:
        raise RuntimeError(f"{name} is required")
    return val

def _melo_language(language: str) -> str:
    lang_map = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JA", "ko": "KO"}
    return lang_map.get(language.lower(), os.getenv("MELO_LANGUAGE", "EN"))

def _ensure_checkpoints() -> Tuple[str, str, str]:
    root = _env("OPENVOICE_CHECKPOINTS_V2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "tone_color_converter")
    if not os.path.isdir(base_root):
        raise RuntimeError(f"Missing MeloTTS base_speakers at {base_root}")
    if not os.path.isdir(conv_root):
        raise RuntimeError(f"Missing tone_color_converter at {conv_root}")
    return root, base_root, conv_root

def _find_converter_ckpt(conv_root: str) -> str:
    for pattern in ("*.pth", "**/*.pth", "*.pt", "**/*.pt"):
        matches = glob.glob(os.path.join(conv_root, pattern), recursive=True)
        if matches:
            return matches[0]
    raise RuntimeError(f"No converter checkpoint (*.pth|*.pt) found under {conv_root}")

def _pick_base_se_path(lang: str, base_root: str) -> str:
    """
    Pick a base speaker embedding .pth under base_speakers/ses for the language.
    """
    ses_dir = os.path.join(base_root, "ses")
    if not os.path.isdir(ses_dir):
        raise RuntimeError(f"Missing base_speakers/ses at {ses_dir}")
    lang = lang.lower()
    candidates = {
        "en": ["en-us.pth", "en-default.pth", "en-newest.pth", "en-au.pth", "en-br.pth", "en-india.pth"],
        "es": ["es.pth"],
        "fr": ["fr.pth"],
        "zh": ["zh.pth"],
        "ja": ["jp.pth"],
        "ko": ["kr.pth"],
    }.get(lang, [])
    for name in candidates:
        p = os.path.join(ses_dir, name)
        if os.path.isfile(p):
            return p
    # fallback: first .pth we can find
    for name in sorted(os.listdir(ses_dir)):
        if name.endswith(".pth"):
            return os.path.join(ses_dir, name)
    raise RuntimeError(f"No *.pth speaker embedding found in {ses_dir}")

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

def _maybe_add_language_kw(fn: Callable[..., Any], kwargs: Dict[str, Any], language: str) -> None:
    try:
        sig = inspect.signature(fn)
        if "language" in sig.parameters:
            kwargs["language"] = language
    except Exception:
        pass

def _filter_kwargs_for(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return kwargs
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        allow = {"text", "speaker_id", "speed", "language", "output_path"}
        return {k: v for k, v in kwargs.items() if k in allow}

def _coerce_speaker_id(spk, melo=None) -> int:
    try:
        return int(spk)
    except Exception:
        pass
    if isinstance(spk, str) and spk.isdigit():
        return int(spk)
    # try name lookup
    try:
        spk2id = getattr(getattr(getattr(melo, "hps", None), "data", None), "spk2id", None)
        if isinstance(spk2id, dict):
            if spk in spk2id:
                return int(spk2id[spk])
            key = str(spk).replace("-", "_").lower()
            for k, v in spk2id.items():
                if k.replace("-", "_").lower() == key:
                    return int(v)
    except Exception:
        pass
    return 0

def _build_convert_fn(converter):
    """
    Write Melo audio to temp WAV and call converter with:
        convert(audio_src_path=..., src_se=..., tgt_se=..., output_path=...)
    Falls back to common positional signatures.
    Returns np.float32 ndarray audio.
    """
    import soundfile as _sf
    import numpy as _np
    import tempfile, os

    if not (hasattr(converter, "convert") or hasattr(converter, "tone_color_convert")):
        raise RuntimeError("ToneColorConverter has no convert/tone_color_convert")

    def _convert_any(audio_f32: _np.ndarray, sr: int, src_se, tgt_se) -> _np.ndarray:
        # write input audio to a temp wav
        fd_in, in_wav = tempfile.mkstemp(prefix="ov2-in-", suffix=".wav")
        os.close(fd_in)
        _sf.write(in_wav, _np.asarray(audio_f32, dtype=_np.float32), int(sr))

        fd_out, out_wav = tempfile.mkstemp(prefix="ov2-out-", suffix=".wav")
        os.close(fd_out)

        try:
            if hasattr(converter, "convert"):
                # Named signature (preferred)
                try:
                    converter.convert(
                        audio_src_path=in_wav,
                        src_se=src_se,
                        tgt_se=tgt_se,
                        output_path=out_wav,
                    )
                except TypeError:
                    # Positional: (path, src_se, tgt_se, out_path)
                    try:
                        converter.convert(in_wav, src_se, tgt_se, out_wav)
                    except TypeError:
                        # Positional swapped: (path, tgt_se, src_se, out_path)
                        converter.convert(in_wav, tgt_se, src_se, out_wav)
            else:
                # Very old alt path: tone_color_convert expects ndarray -> return ndarray
                audio2 = converter.tone_color_convert(_np.asarray(audio_f32, dtype=_np.float32), int(sr), tgt_se)  # type: ignore[attr-defined]
                if isinstance(audio2, _np.ndarray):
                    return audio2.astype(_np.float32)

            data, _sr = _sf.read(out_wav, dtype="float32")
            return data.astype(_np.float32)
        finally:
            for p in (in_wav, out_wav):
                try:
                    os.remove(p)
                except Exception:
                    pass

    return _convert_any

def _load_models_once() -> None:
    """
    Version-agnostic loader for MeloTTS + ToneColorConverter.
    """
    _ensure_nltk()
    global _MELO, _CONVERTER, _SPEAKER_ID, _CONVERT_FN
    if _MELO is not None and _CONVERTER is not None and _CONVERT_FN is not None:
        return

    try:
        from melo.api import TTS as MeloTTS          # type: ignore
        from openvoice.api import ToneColorConverter # type: ignore
        from openvoice import se_extractor           # noqa: F401  (import side effect)
    except Exception as e:
        raise RuntimeError(
            "OpenVoice V2 runtime not installed. "
            "Install MeloTTS/OpenVoice and ensure checkpoints_v2 are present. "
            f"Import error: {e}"
        )

    _, _, conv_root = _ensure_checkpoints()
    ckpt = _find_converter_ckpt(conv_root)

    # Melo
    _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))
    _SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "0")

    # Converter (official pattern)
    cfg_path = os.path.join(conv_root, "config.json")
    device = os.getenv("OPENVOICE_DEVICE", "cuda" if os.getenv("CUDA_VISIBLE_DEVICES", "") else "cpu")
    converter = ToneColorConverter(config_path=cfg_path, device=device)  # type: ignore[call-arg]
    if hasattr(converter, "load_ckpt"):
        converter.load_ckpt(ckpt)
    elif hasattr(converter, "load"):
        converter.load(ckpt_path=ckpt)
    else:
        raise RuntimeError("Unsupported ToneColorConverter: missing load/load_ckpt")

    _CONVERT_FN = _build_convert_fn(converter)
    _CONVERTER = converter

def warmup_models() -> None:
    _load_models_once()

def _resolve_melo_audio(
    *,
    tts_obj: Any,
    melo_lang: str,
    text: str,
    speaker_id: int,
    speed: float,
) -> Tuple[np.ndarray, int]:
    """Call Melo using whatever API is available and return (audio, sr)."""
    kwargs: Dict[str, Any] = dict(text=text, speaker_id=int(speaker_id), speed=float(speed))

    # Preferred: tts_to_audio
    if hasattr(tts_obj, "tts_to_audio"):
        fn = tts_obj.tts_to_audio
        _maybe_add_language_kw(fn, kwargs, melo_lang)
        out = fn(**_filter_kwargs_for(fn, kwargs))
        if isinstance(out, tuple) and len(out) == 2:
            audio, sr = out  # type: ignore[misc]
        else:
            audio = out  # type: ignore[assignment]
            sr = getattr(tts_obj, "sample_rate", None) or getattr(tts_obj, "sr", None) or 22050
        return np.asarray(audio, dtype=np.float32), int(sr)

    # Fallback: tts_to_file
    if hasattr(tts_obj, "tts_to_file"):
        fn = tts_obj.tts_to_file
        _maybe_add_language_kw(fn, kwargs, melo_lang)
        fd, tmpwav = tempfile.mkstemp(prefix="melo-out-", suffix=".wav")
        os.close(fd)
        try:
            fn(output_path=tmpwav, **_filter_kwargs_for(fn, kwargs))
            data, sr = sf.read(tmpwav, dtype="float32")
            return np.asarray(data, dtype=np.float32), int(sr)
        finally:
            try:
                os.remove(tmpwav)
            except Exception:
                pass

    # Legacy: tts
    if hasattr(tts_obj, "tts"):
        fn = tts_obj.tts
        _maybe_add_language_kw(fn, kwargs, melo_lang)
        audio = fn(**_filter_kwargs_for(fn, kwargs))
        sr = getattr(tts_obj, "sample_rate", None) or getattr(tts_obj, "sr", None) or 22050
        return np.asarray(audio, dtype=np.float32), int(sr)

    raise RuntimeError("Unsupported MeloTTS build: no tts_to_audio/tts_to_file/tts")

# -------- Public entry --------
async def synthesize_v2_to_wav_path(
    *,
    text: str,
    language: str,
    reference_b64: Optional[str],
    reference_url: Optional[str],
    speed: float,
    volume: float,  # kept for API compatibility; not all Melos support this
    pitch: float,   # kept for API compatibility; not all Melos support this
    metadata: dict,
) -> str:
    # Guards
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

    # Base TTS (Melo)
    melo_lang = _melo_language(lang)
    spk = _coerce_speaker_id(os.getenv("MELO_SPEAKER_ID", "0"), _MELO)
    base_audio, sr = _resolve_melo_audio(
        tts_obj=_MELO, melo_lang=melo_lang, text=text, speaker_id=spk, speed=speed
    )

    # Speaker embeddings
    import torch
    from openvoice import se_extractor

    # target embedding from reference
    try:
        tgt_se, _ = se_extractor.get_se(ref_path, _CONVERTER, vad=True)  # new API returns (se, length)
    except TypeError:
        tgt_se = se_extractor.get_se(ref_path)

    # source embedding from language-specific base speaker
    _, base_root, _ = _ensure_checkpoints()
    src_se_path = _pick_base_se_path(lang, base_root)
    device = os.getenv("OPENVOICE_DEVICE", "cuda" if os.getenv("CUDA_VISIBLE_DEVICES", "") else "cpu")
    src_se = torch.load(src_se_path, map_location=device)

    # Tone color conversion
    converted_audio = _CONVERT_FN(base_audio, sr, src_se, tgt_se)

    # Write WAV (16-bit PCM)
    fd, out_path = tempfile.mkstemp(prefix="june-tts-v2-", suffix=".wav")
    os.close(fd)
    sf.write(out_path, converted_audio, sr, subtype="PCM_16")

    # Cleanup reference file
    async def _cleanup():
        try:
            if os.path.exists(ref_path):
                os.remove(ref_path)
        except Exception:
            pass
    asyncio.create_task(_cleanup())

    return out_path
