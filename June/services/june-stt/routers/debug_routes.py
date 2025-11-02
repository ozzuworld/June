"""Debug and diagnostic routes for June STT"""
from fastapi import APIRouter

from config import config
from whisper_service import whisper_service
from services.orchestrator_client import orchestrator_client
from utils.metrics import streaming_metrics

router = APIRouter(tags=["debug"])

# Global state (injected by main app)
utterance_manager = None
room_manager = None
partial_processor = None

@router.get("/sota-performance")
async def debug_sota_performance():
    """SOTA: Debug endpoint for performance analysis"""
    utterance_stats = utterance_manager.get_stats() if utterance_manager else {}
    room_stats = room_manager.get_stats() if room_manager else {}
    orchestrator_stats = orchestrator_client.get_stats()
    
    return {
        "sota_optimization_status": {
            "sota_mode_enabled": True,
            "ultra_fast_partials": True,
            "aggressive_vad_tuning": True,
        },
        "performance_targets": {
            "first_partial_target_ms": 200,
            "ultra_fast_target_ms": 150,
            "partial_emit_interval_ms": 200,
            "silence_detection_ms": 800,
            "processing_sleep_ms": 30,
        },
        "competitive_benchmarks": {
            "openai_realtime_target_ms": 300,
            "google_gemini_target_ms": 450,
            "our_target_ms": 200,
            "ultra_fast_target_ms": 150,
            "competitive_status": "INDUSTRY_LEVEL",
        },
        "optimization_achievements": utterance_stats,
        "streaming_config": {
            "STREAMING_ENABLED": True,
            "PARTIALS_ENABLED": True,
            "CONTINUOUS_PARTIALS": True,
        },
        "timing_optimizations": {
            "PARTIAL_EMIT_INTERVAL_MS": "200 (was 250ms)",
            "PARTIAL_MIN_SPEECH_MS": "200 (was 300ms)", 
            "SILENCE_TIMEOUT_SEC": "0.8 (was 1.2s)",
            "PROCESS_SLEEP_SEC": "0.03 (was 0.05s)",
            "MAX_UTTERANCE_SEC": "8.0 (was 12.0s)",
            "MIN_UTTERANCE_SEC": "0.3 (was 0.5s)",
        },
        "connectivity": {
            "room_connected": room_stats.get("connected", False),
            "orchestrator_available": orchestrator_stats.get("available", False),
            "orchestrator_url": config.ORCHESTRATOR_URL,
        },
        "current_state": {
            "whisper_ready": whisper_service.is_model_ready(),
            "room_stats": room_stats,
            "utterance_stats": utterance_stats,
            "orchestrator_stats": orchestrator_stats,
        },
        "performance_metrics": {
            "streaming_stats": streaming_metrics.get_stats(),
        },
    }


def inject_dependencies(um, rm, pp):
    """Inject dependencies from main app"""
    global utterance_manager, room_manager, partial_processor
    utterance_manager = um
    room_manager = rm
    partial_processor = pp
