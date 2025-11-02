"""Orchestrator client service for June STT"""
import uuid
import httpx
import logging
from datetime import datetime
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

class OrchestratorClient:
    """Manages communication with the orchestrator service"""
    
    def __init__(self):
        self.available = False
        self.partial_transcripts_sent = 0
        
    async def check_health(self) -> bool:
        """Check if orchestrator is available"""
        if not config.ORCHESTRATOR_URL:
            return False
            
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{config.ORCHESTRATOR_URL}/healthz")
                self.available = r.status_code == 200
                return self.available
        except Exception:
            self.available = False
            return False
    
    async def notify_transcript(self, user_id: str, text: str, language: Optional[str], 
                              partial: bool = False, utterance_id: Optional[str] = None, 
                              partial_sequence: int = 0, sota_optimized: bool = False):
        """Send transcript notification to orchestrator"""
        if not config.ORCHESTRATOR_URL:
            logger.debug("Orchestrator URL not configured, skipping notification")
            return

        payload = {
            "transcript_id": str(uuid.uuid4()),
            "user_id": user_id,
            "participant": user_id,
            "event": "partial_transcript" if partial else "transcript",
            "text": text,
            "language": language,
            "timestamp": datetime.utcnow().isoformat(),
            "room_name": "ozzu-main",
            "partial": partial,
        }
        
        # Enhanced streaming metadata
        if partial:
            payload.update({
                "utterance_id": utterance_id,
                "partial_sequence": partial_sequence,
                "is_streaming": True,
                "sota_optimized": sota_optimized,
                "streaming_metadata": {
                    "chunk_duration_ms": 150,
                    "min_speech_ms": 200,
                    "emit_interval_ms": 200,
                    "sota_mode": True,
                    "ultra_fast_partials": True,
                    "performance_tier": "sota_competitive"
                }
            })

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.post(f"{config.ORCHESTRATOR_URL}/api/webhooks/stt", json=payload)
                
                if r.status_code == 429:
                    logger.info(f"🛑️ Rate limited by orchestrator: {r.text}")
                    self.available = True
                elif r.status_code != 200:
                    logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
                    self.available = False
                else:
                    status = '⚡ SOTA PARTIAL' if partial else '📤 FINAL'
                    if sota_optimized:
                        status += ' (OPTIMIZED)'
                    logger.info(f"{status} transcript to orchestrator: '{text}'")
                    self.available = True
                    if partial:
                        self.partial_transcripts_sent += 1
                        
        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logger.warning(f"⏰ Orchestrator timeout ({type(e).__name__}): {e}")
            self.available = False
        except httpx.ConnectError as e:
            logger.warning(f"🔌 Orchestrator connection error: {e}")
            self.available = False
        except Exception as e:
            logger.warning(f"❌ Orchestrator notify error: {e}")
            self.available = False
    
    def get_stats(self) -> dict:
        """Get orchestrator client statistics"""
        return {
            "available": self.available,
            "partial_transcripts_sent": self.partial_transcripts_sent,
            "url_configured": bool(config.ORCHESTRATOR_URL)
        }

# Global orchestrator client instance
orchestrator_client = OrchestratorClient()

# Convenience function for backward compatibility
async def notify_orchestrator(*args, **kwargs):
    """Convenience function for notifying orchestrator"""
    return await orchestrator_client.notify_transcript(*args, **kwargs)
