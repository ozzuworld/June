from fastapi import APIRouter, Query
from typing import Optional, Dict, Any
from app.core.openvoice_engine import synthesize_v2_to_wav_path

router = APIRouter(prefix="/voices", tags=["voices-fulltest"])

@router.get("/fulltest")
async def fulltest(
    language: str = "en",
    speaker_id: Optional[int] = None,
    reference_url: str = "https://cdn.jsdelivr.net/gh/myshell-ai/OpenVoice/resources/example_reference.mp3"
) -> Dict[str, Any]:
    """
    End-to-end test using a public reference clip and short text.
    Returns path on disk; use only for sanity checks (not a long-term API).
    """
    wav_path = await synthesize_v2_to_wav_path(
        text="This is a full pipeline test for OpenVoice version two.",
        language=language,
        speaker_id=speaker_id,
        reference_b64=None,
        reference_url=reference_url,
        speed=1.0, volume=1.0, pitch=0.0,
        metadata={}
    )
    return {"ok": True, "wav_path": wav_path}
