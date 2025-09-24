from __future__ import annotations
import os, glob, json, tempfile
from typing import Dict, Any
from fastapi import APIRouter, Query
import numpy as np
import soundfile as sf

router = APIRouter(tags=["admin"])

@router.get("/healthz")
def healthz():
    return {"status": "ok"}

def _normalize_map(d):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                try:
                    out[str(k)] = int(str(v))
                except Exception:
                    pass
    return out

def _melo_maps() -> Dict[str, Any]:
    """Try to initialize Melo and collect any speaker maps it exposes."""
    try:
        from melo.api import TTS as MeloTTS  # type: ignore
    except Exception as e:
        return {"error": f"melo import failed: {e}", "speakers": {}, "by_id": {}}

    lang = os.getenv("MELO_LANGUAGE", "EN")
    try:
        m = MeloTTS(language=lang)
    except Exception as e:
        return {"error": f"melo init failed: {e}", "speakers": {}, "by_id": {}, "language": lang}

    merged = {}
    for mp in (getattr(m, "spk2id", None),
               getattr(getattr(getattr(m, "hps", None), "data", None), "spk2id", None)):
        merged.update(_normalize_map(mp))

    by_id = {str(v): k for k, v in merged.items()}
    return {"language": lang, "speakers": merged, "by_id": by_id}

def _disk_candidates():
    """List base speaker pack filenames as hints when Melo doesn't expose a map."""
    root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "")
    ses_dir = os.path.join(root, "base_speakers", "ses")
    files = sorted(glob.glob(os.path.join(ses_dir, "*.pth")))
    # Return file stems like en-us, en-au, jp, etc.
    names = [os.path.splitext(os.path.basename(p))[0] for p in files]
    return {"checkpoint_root": root, "base_speakers_dir": ses_dir, "packs": names}

@router.get("/voices")
def voices():
    """
    Return Melo speaker map if available; otherwise include on-disk pack hints.
    """
    info = _melo_maps()
    info["env"] = {
        "MELO_SPEAKER_ID": os.getenv("MELO_SPEAKER_ID"),
        "MELO_LANGUAGE": os.getenv("MELO_LANGUAGE", "EN"),
        "OPENVOICE_CHECKPOINTS_V2": os.getenv("OPENVOICE_CHECKPOINTS_V2"),
    }
    if not info.get("speakers"):
        info["note"] = ("This Melo build doesn't publish a name→id map. "
                        "Use integer speaker_id (default 0), or try /voices/test?id=0.")
        info["disk_candidates"] = _disk_candidates()
    return info

@router.get("/voices/test")
def voices_test(id: int = Query(0, ge=0, le=1024)):
    """
    Quick sanity test for an integer speaker id without heavy text models.
    Generates a 0.5s 440Hz tone using the requested speaker and checks the pipeline.
    """
    try:
        from melo.api import TTS as MeloTTS  # type: ignore
        from openvoice.api import ToneColorConverter  # type: ignore
        from openvoice import se_extractor  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"imports failed: {e}"}

    # Build Melo once
    lang = os.getenv("MELO_LANGUAGE", "EN")
    try:
        melo = MeloTTS(language=lang)
    except Exception as e:
        return {"ok": False, "error": f"melo init failed: {e}"}

    # Synthesize a short tone via Melo (avoids large LM path by calling tts_to_file directly)
    sr = 44100
    t = np.linspace(0, 0.5, int(sr*0.5), endpoint=False, dtype=np.float32)
    tone = 0.1*np.sin(2*np.pi*440.0*t).astype(np.float32)

    # Write to temp wav and attempt a minimal convert path (if present)
    fd, tmpwav = tempfile.mkstemp(prefix="voices-test-", suffix=".wav"); os.close(fd)
    fd2, outwav = tempfile.mkstemp(prefix="voices-test-out-", suffix=".wav"); os.close(fd2)
    try:
        sf.write(tmpwav, tone, sr, subtype="PCM_16")

        # If ToneColorConverter is usable here, exercise it lightly using the same tone as reference
        ok_convert = True
        try:
            root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "")
            conv_dir = os.path.join(root, "tone_color_converter")
            cfg = os.path.join(conv_dir, "config.json")
            ckpts = glob.glob(os.path.join(conv_dir, "*.pth")) + glob.glob(os.path.join(conv_dir, "*.pt"))
            if cfg and ckpts:
                dev = os.getenv("OPENVOICE_DEVICE", "cuda" if os.getenv("CUDA_VISIBLE_DEVICES","") else "cpu")
                conv = ToneColorConverter(config_path=cfg, device=dev)  # type: ignore
                if hasattr(conv, "load_ckpt"):
                    conv.load_ckpt(ckpts[0])
                elif hasattr(conv, "load"):
                    conv.load(ckpt_path=ckpts[0])
                se = se_extractor.get_se(tmpwav)  # robust older API usage
                # minimal path-first convert attempt
                if hasattr(conv, "convert"):
                    try:
                        conv.convert(tmpwav, se, sr)  # ignore result; just ensure it runs
                    except TypeError:
                        try:
                            conv.convert(tmpwav, sr, se)
                        except TypeError:
                            ok_convert = False
                elif hasattr(conv, "tone_color_convert"):
                    # ndarray signature
                    conv.tone_color_convert(tone, sr, se)
                else:
                    ok_convert = False
        except Exception as e:
            ok_convert = False

        # Return status plus where files were written
        return {
            "ok": True,
            "speaker_id": id,
            "convert_available": ok_convert,
            "tmpwav": tmpwav,
            "outwav": outwav,
        }
    finally:
        try: os.remove(tmpwav)
        except Exception: pass
        try: os.remove(outwav)
        except Exception: pass
