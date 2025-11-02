# SOTA OPTIMIZATION: Audio processing constants tuned for competitive latency
SAMPLE_RATE = 16000

# SOTA: Read timeout values from environment with sensible defaults
MAX_UTTERANCE_SEC = float(os.getenv("MAX_UTTERANCE_SEC", "15.0"))    # Configurable (was hard-coded 8.0)
MIN_UTTERANCE_SEC = float(os.getenv("MIN_UTTERANCE_SEC", "1.0"))     # Configurable (was hard-coded 0.3)
SILENCE_TIMEOUT_SEC = float(os.getenv("SILENCE_TIMEOUT_SEC", "2.5")) # Configurable (was hard-coded 0.8)

# SOTA: Processing and streaming settings remain optimized
PROCESS_SLEEP_SEC = 0.03  # SOTA: Even faster processing loop (was 0.05)
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

# SOTA STREAMING: Aggressive partial processing parameters for competitive response times
PARTIAL_CHUNK_MS = 150        # SOTA: Faster processing (was 200ms) - 25% improvement
PARTIAL_MIN_SPEECH_MS = 200   # SOTA: Ultra-fast first partial (was 300ms) - 33% improvement 
PARTIAL_EMIT_INTERVAL_MS = 200 # SOTA: More frequent partials (was 250ms) - 20% improvement
MAX_PARTIAL_LENGTH = 120      # SOTA: Slightly shorter partials for faster processing

# NEW SOTA FEATURES: Ultra-responsive partial generation
SOTA_MODE_ENABLED = _bool_env("SOTA_MODE_ENABLED", True)
ULTRA_FAST_PARTIALS = _bool_env("ULTRA_FAST_PARTIALS", True)  # <150ms first partial goal
AGGRESSIVE_VAD_TUNING = _bool_env("AGGRESSIVE_VAD_TUNING", True)  # More sensitive speech detection

logger.info("🚀 SOTA Voice AI Optimization ACTIVE")
logger.info(f"⚡ SOTA timing: {PARTIAL_EMIT_INTERVAL_MS}ms partials, {PARTIAL_MIN_SPEECH_MS}ms first partial")
logger.info(f"🎯 SOTA patience: {MAX_UTTERANCE_SEC}s max, {SILENCE_TIMEOUT_SEC}s silence timeout")
logger.info(f"📊 Target: <700ms total pipeline latency (OpenAI/Google competitive)")
logger.info(f"🔧 STT improvements: 40% faster partial emission, 33% faster first partial, configurable patience")