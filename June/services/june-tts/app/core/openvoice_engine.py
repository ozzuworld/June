"""
Simplified wrapper around the OpenVoice V2 MeloTTS and ToneColorConverter models.

This module provides just two high‑level functions:

* `synthesize_tts` – Generate speech from text using the base speaker.
* `clone_voice` – Generate speech that matches the tone colour of a reference
  audio clip using the tone colour converter.

Unlike the previous implementation, this module does not perform any
quantization, caching, memory logging or experimental voice‑similarity metrics.
It loads the models lazily on first use and reuses them for subsequent calls.

The implementation adheres closely to the guidelines from the OpenVoice V2
documentation, which emphasize that the tone colour converter clones only the
reference speaker's timbre and does not replicate accent or emotion【212231721036567†L296-L305】.
Users should therefore supply a base speaker checkpoint that embodies the
desired accent or emotion, and use clean, single‑speaker reference audio【212231721036567†L294-L315】.
"""

from __future__ import annotations

import io
from typing import Tuple

import numpy as np
import soundfile as sf
import torch

from openvoice import ToneColorConverter  # type: ignore
from openvoice.api import MeloTTS  # type: ignore

from .config import settings

_melo: MeloTTS | None = None
_converter: ToneColorConverter | None = None


def _load_models() -> Tuple[MeloTTS, ToneColorConverter]:
    """Load MeloTTS and ToneColorConverter models if not already loaded."""
    global _melo, _converter
    if _melo is None:
        _melo = MeloTTS.from_pretrained(settings.melo_checkpoint)
    if _converter is None:
        _converter = ToneColorConverter.from_pretrained(settings.converter_checkpoint)
        _converter.eval()
    return _melo, _converter


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Serialize a NumPy float32 audio array to WAV bytes."""
    buf = io.BytesIO()
    sf.write(buf, audio, samplerate=sample_rate, format="WAV")
    return buf.getvalue()


async def synthesize_tts(text: str, language: str = "EN", speed: float = 1.0) -> bytes:
    """
    Synthesize speech from text using the base MeloTTS model.

    Parameters
    ----------
    text: str
        The text to synthesize. Should be plain text without markup.
    language: str
        Language code (e.g. "EN", "ES", "FR"). Must be supported by the
        base speaker model. Defaults to English.
    speed: float
        Speed factor for the generated speech. Values >1.0 speak faster,
        <1.0 speak slower. OpenVoice V2 recommends staying within 0.5–2.0.

    Returns
    -------
    bytes
        WAV‑encoded audio bytes.
    """
    melo, _ = _load_models()
    # Generate audio using the base speaker (speaker_id=0 for default voice)
    try:
        audio, sr = melo.tts_to_audio(text=text, speaker_id=0, language=language, speed=speed)
    except TypeError:
        # Older versions of MeloTTS may not accept language/speed arguments
        audio, sr = melo.tts_to_audio(text=text, speaker_id=0)
    audio_np = np.asarray(audio, dtype=np.float32)
    return _to_wav_bytes(audio_np, sr)


async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "EN",
    speed: float = 1.0,
) -> bytes:
    """
    Clone the tone colour of a reference speaker and generate speech from text.

    This function follows the OpenVoice V2 guidelines: it generates a base
    speech sample from the MeloTTS model and then applies the tone colour
    converter to transfer the reference speaker's timbre onto the base audio.
    The accent and emotion of the output will still derive from the base
    speaker; only the timbre is cloned【212231721036567†L296-L305】.

    Parameters
    ----------
    text: str
        The text to synthesize.
    reference_audio_bytes: bytes
        The raw bytes of a short, clean reference recording of the speaker.
    language: str
        Language code supported by the base speaker. Defaults to "EN".
    speed: float
        Speech speed multiplier.

    Returns
    -------
    bytes
        WAV‑encoded audio bytes.
    """
    melo, converter = _load_models()
    # Decode the reference audio into a tensor
    ref_buf = io.BytesIO(reference_audio_bytes)
    ref_audio, ref_sr = sf.read(ref_buf, dtype="float32")
    ref_tensor = torch.from_numpy(ref_audio).unsqueeze(0)

    # Generate base audio from MeloTTS
    try:
        base_audio, sr = melo.tts_to_audio(text=text, speaker_id=0, language=language, speed=speed)
    except TypeError:
        base_audio, sr = melo.tts_to_audio(text=text, speaker_id=0)
    base_tensor = torch.from_numpy(np.asarray(base_audio, dtype=np.float32)).unsqueeze(0)

    # Apply tone colour conversion. According to the API docs, `voice_conversion`
    # takes the reference and base audio tensors and returns a tensor.
    with torch.no_grad():
        converted_tensor = converter.voice_conversion(ref_tensor, base_tensor)
    converted_np = converted_tensor.squeeze(0).cpu().numpy()
    return _to_wav_bytes(converted_np, sr)