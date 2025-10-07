"""
Configuration for June Voice Cloning Service
"""

import os
from typing import List

class Settings:
    """Application settings"""
    
    # Service settings
    SERVICE_NAME: str = "june-voice-cloning"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # F5-TTS settings
    F5TTS_DEVICE: str = os.getenv("F5TTS_DEVICE", "cuda")
    F5TTS_MODEL_PATH: str = os.getenv("F5TTS_MODEL_PATH", "")
    ENABLE_MODEL_CACHING: bool = os.getenv("ENABLE_MODEL_CACHING", "true").lower() == "true"
    
    # Audio processing settings
    MAX_AUDIO_DURATION: int = int(os.getenv("MAX_AUDIO_DURATION", "15"))  # seconds
    MIN_AUDIO_DURATION: float = float(os.getenv("MIN_AUDIO_DURATION", "1.0"))  # seconds
    TARGET_SAMPLE_RATE: int = int(os.getenv("TARGET_SAMPLE_RATE", "24000"))
    
    # Cache settings
    TRANSFORMERS_CACHE: str = os.getenv("TRANSFORMERS_CACHE", "/tmp/transformers")
    HF_HOME: str = os.getenv("HF_HOME", "/tmp/huggingface")
    HUGGINGFACE_HUB_CACHE: str = os.getenv("HUGGINGFACE_HUB_CACHE", "/tmp/huggingface/hub")
    
    # Performance settings
    CUDA_VISIBLE_DEVICES: str = os.getenv("CUDA_VISIBLE_DEVICES", "0")
    PYTORCH_CUDA_ALLOC_CONF: str = os.getenv("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:256")
    
    # Supported languages
    SUPPORTED_LANGUAGES: List[str] = [
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar",
        "zh-cn", "zh-tw", "ja", "ko", "hi", "th", "vi", "id", "ms"
    ]
    
    # Default reference text for different languages
    DEFAULT_REFERENCE_TEXTS = {
        "en": "This is a clear reference voice for text to speech synthesis.",
        "es": "Esta es una voz de referencia clara para síntesis de texto a voz.",
        "fr": "Ceci est une voix de référence claire pour la synthèse texte-parole.",
        "de": "Dies ist eine klare Referenzstimme für Text-zu-Sprache-Synthese.",
        "it": "Questa è una voce di riferimento chiara per la sintesi text-to-speech.",
        "pt": "Esta é uma voz de referência clara para síntese de texto para fala.",
        "zh-cn": "这是用于文本转语音合成的清晰参考语音。",
        "ja": "これはテキスト読み上げ合成のための明確な参照音声です。",
        "ko": "이것은 텍스트 음성 변환 합성을 위한 명확한 참조 음성입니다."
    }

    def get_default_reference_text(self, language: str) -> str:
        """Get default reference text for language"""
        return self.DEFAULT_REFERENCE_TEXTS.get(
            language, 
            self.DEFAULT_REFERENCE_TEXTS["en"]
        )

# Global settings instance
settings = Settings()
