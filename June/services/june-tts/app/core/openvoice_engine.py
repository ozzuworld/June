import torch
import asyncio
import tempfile
import os
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager
import warnings
import gc
import time

warnings.filterwarnings("ignore")

try:
    from openvoice import se_extractor
    from openvoice.api import ToneColorConverter
    OPENVOICE_AVAILABLE = True
except ImportError:
    OPENVOICE_AVAILABLE = False

try:
    from melo.api import TTS
    MELO_AVAILABLE = True
except ImportError:
    MELO_AVAILABLE = False

from app.core.config import settings

class OpenVoiceEngine:
    def __init__(self):
        self.device = self._smart_device_init()
        self.converter: Optional[ToneColorConverter] = None
        self.tts_models: dict[str, TTS] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        
    def _smart_device_init(self):
        """Smart device initialization that handles CUDA context issues"""
        if not torch.cuda.is_available():
            print("⚠️  CUDA not available, using CPU")
            return "cpu"
            
        try:
            # Set environment for stability
            os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
            os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:256'
            
            # Try multiple times to establish context
            for attempt in range(3):
                try:
                    # Force context creation without memory query
                    torch.cuda.set_device(0)
                    
                    # Create a small tensor to establish context
                    test_tensor = torch.tensor([1.0], device='cuda')
                    result = test_tensor + 1
                    
                    # If we get here, CUDA works
                    del test_tensor, result
                    torch.cuda.empty_cache()
                    
                    print(f"✅ GPU initialized: {torch.cuda.get_device_name(0)}")
                    # Skip memory query that causes issues
                    print("🔥 GPU ready (memory check skipped to avoid context issues)")
                    return "cuda"
                    
                except RuntimeError as e:
                    if "busy or unavailable" in str(e):
                        print(f"⚠️  CUDA context attempt {attempt + 1} failed, retrying...")
                        time.sleep(1)
                        torch.cuda.empty_cache()
                        gc.collect()
                    else:
                        raise e
                        
            # If all attempts failed, use CPU
            print("⚠️  CUDA context creation failed, falling back to CPU")
            return "cpu"
            
        except Exception as e:
            print(f"⚠️  GPU initialization failed: {e}")
            return "cpu"
        
    async def initialize(self):
        """Initialize OpenVoice models"""
        try:
            print(f"🔧 Initializing OpenVoice engine on {self.device}")
            
            if self.device == "cuda":
                # Set optimizations for RTX 3060 Ti
                torch.backends.cudnn.benchmark = True
                torch.backends.cuda.matmul.allow_tf32 = True
            
            checkpoints_path = Path(settings.checkpoints_path)
            if not checkpoints_path.exists():
                raise FileNotFoundError(f"Checkpoints directory not found: {checkpoints_path}")
            
            # Initialize converter
            if OPENVOICE_AVAILABLE:
                await self._initialize_converter()
            
            # Load initial TTS model
            if MELO_AVAILABLE:
                await self._load_initial_tts()
            
            print(f"✅ OpenVoice engine initialized successfully on {self.device}")
            
        except Exception as e:
            print(f"❌ Engine error: {e}")
    
    async def _initialize_converter(self):
        """Initialize converter with context-aware error handling"""
        try:
            converter_path = Path(settings.checkpoints_path) / "converter"
            config_file = converter_path / "config.json"
            checkpoint_file = converter_path / "checkpoint.pth"
            
            if config_file.exists() and checkpoint_file.exists():
                print(f"🔄 Loading converter on {self.device}...")
                
                # Clear memory before loading
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                
                self.converter = ToneColorConverter(str(config_file), device=self.device)
                self.converter.load_ckpt(str(checkpoint_file))
                print(f"✅ Converter loaded successfully on {self.device}")
            
        except Exception as e:
            print(f"⚠️  Converter failed: {e}")
            self.converter = None
    
    async def _load_initial_tts(self):
        """Load initial TTS model"""
        try:
            print(f"🔄 Loading initial English TTS on {self.device}...")
            
            if self.device == "cuda":
                torch.cuda.empty_cache()
                
            model = TTS(language="EN", device=self.device)
            self.tts_models["EN"] = model
            print(f"✅ English TTS loaded successfully on {self.device}")
            
        except Exception as e:
            print(f"⚠️  Initial TTS load failed: {e}")
    
    async def get_tts_model(self, language: str):
        """Load TTS model on demand"""
        if not MELO_AVAILABLE:
            raise RuntimeError("MeloTTS not available")
            
        if language not in self.tts_models:
            print(f"🔄 Loading TTS for {language} on {self.device}...")
            
            if self.device == "cuda":
                torch.cuda.empty_cache()
                
            model = TTS(language=language, device=self.device)
            self.tts_models[language] = model
            print(f"✅ TTS loaded for {language}")
            
        return self.tts_models[language]
    
    @asynccontextmanager
    async def _request_context(self):
        async with self._semaphore:
            if self.device == "cuda":
                torch.cuda.empty_cache()
            yield
            if self.device == "cuda":
                torch.cuda.empty_cache()
    
    async def text_to_speech(self, text: str, language: str = "EN", speaker_key: Optional[str] = None, speed: float = 1.0) -> bytes:
        if not MELO_AVAILABLE:
            raise RuntimeError("MeloTTS not available")
            
        async with self._request_context():
            try:
                model = await self.get_tts_model(language)
                
                if not speaker_key:
                    speaker_ids = model.hps.data.spk2id
                    speaker_key = list(speaker_ids.keys())[0] if speaker_ids else "default"
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, model.tts_to_file, text, speaker_key, tmp_path, speed)
                
                with open(tmp_path, "rb") as f:
                    audio_data = f.read()
                
                os.unlink(tmp_path)
                return audio_data
                
            except Exception as e:
                raise RuntimeError(f"TTS failed: {str(e)}")
    
    async def clone_voice(self, text: str, reference_audio_bytes: bytes, language: str = "EN", speed: float = 1.0) -> bytes:
        if not self.converter:
            raise RuntimeError("Voice cloning not available")
            
        async with self._request_context():
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
                    ref_file.write(reference_audio_bytes)
                    ref_path = ref_file.name
                
                loop = asyncio.get_event_loop()
                target_se, _ = await loop.run_in_executor(None, se_extractor.get_se, ref_path, self.converter, True)
                
                model = await self.get_tts_model(language)
                speaker_ids = model.hps.data.spk2id
                speaker_key = list(speaker_ids.keys())[0] if speaker_ids else "default"
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as src_file:
                    src_path = src_file.name
                
                await loop.run_in_executor(None, model.tts_to_file, text, speaker_key, src_path, speed)
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_file:
                    out_path = out_file.name
                
                base_speakers_path = Path(settings.checkpoints_path) / "base_speakers" / "ses"
                source_se_path = base_speakers_path / f"{language.lower()}-default.pth"
                
                if not source_se_path.exists():
                    available = list(base_speakers_path.glob("*.pth"))
                    if available:
                        source_se_path = available[0]
                    else:
                        raise FileNotFoundError("No base speaker embeddings found")
                
                source_se = torch.load(str(source_se_path), map_location=self.device)
                
                await loop.run_in_executor(None, self.converter.convert, src_path, source_se, target_se, out_path)
                
                with open(out_path, "rb") as f:
                    result_audio = f.read()
                
                for path in [ref_path, src_path, out_path]:
                    try:
                        os.unlink(path)
                    except:
                        pass
                
                return result_audio
                
            except Exception as e:
                raise RuntimeError(f"Voice cloning failed: {str(e)}")

engine = OpenVoiceEngine()
