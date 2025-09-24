from fastapi import APIRouter, Query
from typing import List, Dict, Any
import tempfile, os, soundfile as sf, numpy as np

from app.core.openvoice_engine import _load_models_once, _MELO, _melo_language, _coerce_speaker_id

router = APIRouter(prefix="/voices", tags=["voices-extra"])

@router.get("/scan")
def scan_speakers(
    start: int = Query(0, ge=0),
    end: int = Query(7, ge=0),
    language: str = Query("en")
) -> Dict[str, Any]:
    """
    Probe integer speaker ids in [start, end] using Melo only.
    Returns which ids synthesize successfully and basic audio stats.
    """
    _load_models_once()
    if _MELO is None:
        return {"ok": False, "error": "Melo not loaded"}

    ok_ids: List[int] = []
    stats: Dict[int, Dict[str, Any]] = {}
    melo_lang = _melo_language(language)

    text = "voice scan."
    for i in range(start, end + 1):
        fd, tmpwav = tempfile.mkstemp(prefix=f"melo-scan-{i}-", suffix=".wav")
        os.close(fd)
        try:
            # call the most compatible API on Melo
            if hasattr(_MELO, "tts_to_file"):
                try:
                    _MELO.tts_to_file(text=text, speaker_id=int(i), speed=1.0, language=melo_lang, output_path=tmpwav)
                except TypeError:
                    # older Melo may not accept language kw
                    _MELO.tts_to_file(text=text, speaker_id=int(i), speed=1.0, output_path=tmpwav)
            elif hasattr(_MELO, "tts_to_audio"):
                try:
                    audio, sr = _MELO.tts_to_audio(text=text, speaker_id=int(i), speed=1.0, language=melo_lang)
                except TypeError:
                    audio, sr = _MELO.tts_to_audio(text=text, speaker_id=int(i), speed=1.0)
                sf.write(tmpwav, np.asarray(audio, dtype=np.float32), int(sr))
            else:
                # legacy tts()
                try:
                    audio = _MELO.tts(text=text, speaker_id=int(i), speed=1.0, language=melo_lang)
                except TypeError:
                    audio = _MELO.tts(text=text, speaker_id=int(i), speed=1.0)
                sr = getattr(_MELO, "sample_rate", None) or getattr(_MELO, "sr", None) or 22050
                sf.write(tmpwav, np.asarray(audio, dtype=np.float32), int(sr))

            # read duration
            data, sr = sf.read(tmpwav, dtype="float32")
            dur = len(data) / float(sr) if sr else 0.0
            if dur > 0.2:  # arbitrary 'works' threshold
                ok_ids.append(i)
                stats[i] = {"duration_sec": round(dur, 3), "sr": sr, "samples": len(data)}
        except Exception as e:
            stats[i] = {"error": str(e)}
        finally:
            try:
                os.remove(tmpwav)
            except Exception:
                pass

    return {"ok": True, "language": melo_lang, "range": [start, end], "working_ids": ok_ids, "stats": stats}
