# app/core/enhanced_voice_features.py - Advanced voice processing features
import asyncio
import time
import numpy as np
import librosa
from typing import List, Dict, Any, Optional, AsyncGenerator
import logging
from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue
import tempfile
import os

logger = logging.getLogger(__name__)

class VoiceSimilarityScorer:
    """Calculate voice similarity and quality metrics"""
    
    def __init__(self):
        self.initialized = False
        self._init_similarity_model()
    
    def _init_similarity_model(self):
        """Initialize voice similarity calculation"""
        try:
            # Use spectral features for similarity scoring
            self.initialized = True
            logger.info("✅ Voice similarity scorer initialized")
        except Exception as e:
            logger.warning(f"⚠️ Voice similarity scorer init failed: {e}")
    
    def calculate_similarity(self, reference_audio: np.ndarray, generated_audio: np.ndarray, sr: int = 22050) -> Dict[str, float]:
        """
        Calculate comprehensive voice similarity metrics
        """
        if not self.initialized:
            return {"error": "Similarity scorer not initialized"}
        
        try:
            metrics = {}
            
            # 1. Spectral similarity
            ref_spec = librosa.feature.melspectrogram(y=reference_audio, sr=sr, n_mels=80)
            gen_spec = librosa.feature.melspectrogram(y=generated_audio, sr=sr, n_mels=80)
            
            # Align spectrograms to same length
            min_frames = min(ref_spec.shape[1], gen_spec.shape[1])
            ref_spec = ref_spec[:, :min_frames]
            gen_spec = gen_spec[:, :min_frames]
            
            # Spectral cosine similarity
            ref_flat = ref_spec.flatten()
            gen_flat = gen_spec.flatten()
            
            dot_product = np.dot(ref_flat, gen_flat)
            norm_ref = np.linalg.norm(ref_flat)
            norm_gen = np.linalg.norm(gen_flat)
            
            if norm_ref > 0 and norm_gen > 0:
                spectral_similarity = dot_product / (norm_ref * norm_gen)
            else:
                spectral_similarity = 0.0
            
            metrics["spectral_similarity"] = float(np.clip(spectral_similarity, 0, 1))
            
            # 2. Pitch similarity
            ref_pitch = librosa.yin(reference_audio, fmin=80, fmax=400, sr=sr)
            gen_pitch = librosa.yin(generated_audio, fmin=80, fmax=400, sr=sr)
            
            # Remove zeros and invalid values
            ref_pitch_valid = ref_pitch[ref_pitch > 0]
            gen_pitch_valid = gen_pitch[gen_pitch > 0]
            
            if len(ref_pitch_valid) > 0 and len(gen_pitch_valid) > 0:
                ref_mean_pitch = np.mean(ref_pitch_valid)
                gen_mean_pitch = np.mean(gen_pitch_valid)
                pitch_diff = abs(ref_mean_pitch - gen_mean_pitch) / ref_mean_pitch
                pitch_similarity = max(0, 1 - pitch_diff)
            else:
                pitch_similarity = 0.5
            
            metrics["pitch_similarity"] = float(pitch_similarity)
            
            # 3. Rhythm similarity (tempo and beat tracking)
            ref_tempo, _ = librosa.beat.beat_track(y=reference_audio, sr=sr)
            gen_tempo, _ = librosa.beat.beat_track(y=generated_audio, sr=sr)
            
            tempo_diff = abs(ref_tempo - gen_tempo) / ref_tempo if ref_tempo > 0 else 1.0
            rhythm_similarity = max(0, 1 - tempo_diff)
            metrics["rhythm_similarity"] = float(rhythm_similarity)
            
            # 4. Formant similarity (voice timbre)
            ref_mfcc = librosa.feature.mfcc(y=reference_audio, sr=sr, n_mfcc=13)
            gen_mfcc = librosa.feature.mfcc(y=generated_audio, sr=sr, n_mfcc=13)
            
            # Align MFCCs
            min_frames = min(ref_mfcc.shape[1], gen_mfcc.shape[1])
            ref_mfcc = ref_mfcc[:, :min_frames]
            gen_mfcc = gen_mfcc[:, :min_frames]
            
            # Calculate correlation for each MFCC coefficient
            formant_correlations = []
            for i in range(ref_mfcc.shape[0]):
                corr = np.corrcoef(ref_mfcc[i], gen_mfcc[i])[0, 1]
                if not np.isnan(corr):
                    formant_correlations.append(abs(corr))
            
            formant_similarity = np.mean(formant_correlations) if formant_correlations else 0.0
            metrics["formant_similarity"] = float(formant_similarity)
            
            # 5. Overall similarity score (weighted average)
            overall_score = (
                metrics["spectral_similarity"] * 0.3 +
                metrics["pitch_similarity"] * 0.3 +
                metrics["rhythm_similarity"] * 0.2 +
                metrics["formant_similarity"] * 0.2
            )
            metrics["overall_similarity"] = float(overall_score)
            
            # 6. Quality metrics
            metrics["audio_quality"] = self._calculate_audio_quality(generated_audio, sr)
            
            logger.info(f"✅ Similarity calculated: {overall_score:.3f}")
            return metrics
            
        except Exception as e:
            logger.error(f"❌ Similarity calculation failed: {e}")
            return {"error": str(e), "overall_similarity": 0.0}
    
    def _calculate_audio_quality(self, audio: np.ndarray, sr: int) -> Dict[str, float]:
        """Calculate audio quality metrics"""
        try:
            quality = {}
            
            # Signal-to-noise ratio estimation
            audio_power = np.mean(audio ** 2)
            noise_estimate = np.var(audio[-int(0.1 * sr):])  # Use last 0.1s as noise estimate
            snr = 10 * np.log10(audio_power / noise_estimate) if noise_estimate > 0 else 60
            quality["snr_db"] = float(np.clip(snr, 0, 60))
            
            # Dynamic range
            dynamic_range = 20 * np.log10(np.max(np.abs(audio)) / (np.mean(np.abs(audio)) + 1e-8))
            quality["dynamic_range_db"] = float(dynamic_range)
            
            # Clipping detection
            clipping_ratio = np.sum(np.abs(audio) > 0.95) / len(audio)
            quality["clipping_ratio"] = float(clipping_ratio)
            
            # Overall quality score (0-1)
            quality_score = (
                min(snr / 40, 1.0) * 0.6 +  # SNR contribution
                (1 - clipping_ratio) * 0.4   # No clipping contribution
            )
            quality["overall_quality"] = float(quality_score)
            
            return quality
            
        except Exception as e:
            logger.error(f"❌ Quality calculation failed: {e}")
            return {"overall_quality": 0.5}

class RealTimeVoiceProcessor:
    """Real-time voice conversion and streaming"""
    
    def __init__(self, chunk_duration: float = 0.5):
        self.chunk_duration = chunk_duration
        self.sample_rate = 22050
        self.chunk_size = int(chunk_duration * self.sample_rate)
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.processing = False
        self.processor_thread = None
        
    async def start_real_time_processing(self, reference_audio_path: str) -> None:
        """Start real-time voice processing"""
        try:
            # Load reference voice embedding
            from openvoice import se_extractor
            from app.core.openvoice_engine import _CONVERTER
            
            if not _CONVERTER:
                raise RuntimeError("Voice converter not available")
            
            self.target_se, _ = se_extractor.get_se(reference_audio_path, _CONVERTER, vad=True)
            
            self.processing = True
            self.processor_thread = threading.Thread(target=self._process_audio_chunks)
            self.processor_thread.start()
            
            logger.info("✅ Real-time voice processing started")
            
        except Exception as e:
            logger.error(f"❌ Failed to start real-time processing: {e}")
            raise
    
    def _process_audio_chunks(self):
        """Process audio chunks in real-time"""
        try:
            from app.core.openvoice_engine import _CONVERTER
            
            while self.processing:
                try:
                    # Get audio chunk from queue (blocking with timeout)
                    chunk = self.input_queue.get(timeout=0.1)
                    
                    if chunk is None:  # Shutdown signal
                        break
                    
                    # Apply voice conversion to chunk
                    converted_chunk = _CONVERTER.convert(
                        audio=chunk.astype(np.float32),
                        sample_rate=self.sample_rate,
                        src_se=self.target_se
                    )
                    
                    # Put processed chunk in output queue
                    self.output_queue.put(converted_chunk)
                    
                except Exception as e:
                    if self.processing:  # Only log if we're still supposed to be processing
                        logger.warning(f"⚠️ Chunk processing error: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Real-time processor crashed: {e}")
    
    async def process_audio_chunk(self, audio_chunk: np.ndarray) -> Optional[np.ndarray]:
        """Add audio chunk for processing and get result"""
        try:
            if not self.processing:
                return None
            
            # Add chunk to input queue
            self.input_queue.put(audio_chunk)
            
            # Try to get processed result (non-blocking)
            try:
                return self.output_queue.get_nowait()
            except:
                return None  # No result ready yet
                
        except Exception as e:
            logger.error(f"❌ Chunk processing failed: {e}")
            return None
    
    async def stop_real_time_processing(self):
        """Stop real-time processing"""
        try:
            self.processing = False
            
            # Send shutdown signal
            self.input_queue.put(None)
            
            # Wait for processor thread to finish
            if self.processor_thread:
                self.processor_thread.join(timeout=5.0)
            
            # Clear queues
            while not self.input_queue.empty():
                try:
                    self.input_queue.get_nowait()
                except:
                    break
            
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                except:
                    break
            
            logger.info("✅ Real-time processing stopped")
            
        except Exception as e:
            logger.error(f"❌ Failed to stop real-time processing: {e}")

class BatchVoiceProcessor:
    """Batch processing for multiple voice synthesis tasks"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
    async def process_batch(
        self, 
        tasks: List[Dict[str, Any]],
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Process multiple TTS/voice cloning tasks in parallel
        
        Args:
            tasks: List of task dictionaries with keys:
                - text: str
                - language: str  
                - reference_audio: Optional[str] (file path or base64)
                - speed: float
                - output_path: Optional[str]
            progress_callback: Optional callback for progress updates
        """
        try:
            logger.info(f"🚀 Starting batch processing of {len(tasks)} tasks")
            
            # Prepare tasks for parallel execution
            futures = []
            for i, task in enumerate(tasks):
                future = asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self._process_single_task,
                    task,
                    i
                )
                futures.append(future)
            
            # Process tasks and collect results
            results = []
            completed = 0
            
            for future in asyncio.as_completed(futures):
                try:
                    result = await future
                    results.append(result)
                    completed += 1
                    
                    # Report progress
                    if progress_callback:
                        progress = completed / len(tasks)
                        progress_callback(progress, completed, len(tasks))
                    
                    logger.info(f"✅ Completed task {completed}/{len(tasks)}")
                    
                except Exception as e:
                    logger.error(f"❌ Task failed: {e}")
                    results.append({
                        "success": False,
                        "error": str(e),
                        "task_id": len(results)
                    })
                    completed += 1
            
            # Sort results by original task order
            results.sort(key=lambda x: x.get("task_id", 0))
            
            success_count = sum(1 for r in results if r.get("success", False))
            logger.info(f"🎉 Batch processing complete: {success_count}/{len(tasks)} successful")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Batch processing failed: {e}")
            return [{"success": False, "error": str(e)} for _ in tasks]
    
    def _process_single_task(self, task: Dict[str, Any], task_id: int) -> Dict[str, Any]:
        """Process a single TTS task (runs in thread pool)"""
        try:
            start_time = time.time()
            
            # Import here to avoid circular imports
            import asyncio
            from app.core.openvoice_engine import synthesize_v2_to_wav_path
            
            # Extract task parameters
            text = task.get("text", "")
            language = task.get("language", "en")
            reference_audio = task.get("reference_audio")
            speed = task.get("speed", 1.0)
            output_path = task.get("output_path")
            
            if not text.strip():
                raise ValueError("Empty text")
            
            # Determine if using voice cloning
            reference_b64 = None
            reference_url = None
            
            if reference_audio:
                if reference_audio.startswith("http"):
                    reference_url = reference_audio
                elif reference_audio.startswith("data:") or len(reference_audio) > 500:
                    reference_b64 = reference_audio
                else:
                    # Assume file path, convert to base64
                    try:
                        with open(reference_audio, "rb") as f:
                            import base64
                            reference_b64 = base64.b64encode(f.read()).decode()
                    except Exception as e:
                        logger.warning(f"⚠️ Could not read reference file: {e}")
            
            # Run synthesis in async context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result_path = loop.run_until_complete(
                    synthesize_v2_to_wav_path(
                        text=text,
                        language=language,
                        reference_b64=reference_b64,
                        reference_url=reference_url,
                        speed=speed,
                        volume=1.0,
                        pitch=0.0,
                        metadata={"task_id": task_id}
                    )
                )
            finally:
                loop.close()
            
            # Move to final output path if specified
            final_path = result_path
            if output_path:
                import shutil
                shutil.move(result_path, output_path)
                final_path = output_path
            
            processing_time = time.time() - start_time
            
            return {
                "success": True,
                "task_id": task_id,
                "output_path": final_path,
                "processing_time": processing_time,
                "text_length": len(text),
                "used_voice_cloning": bool(reference_audio)
            }
            
        except Exception as e:
            logger.error(f"❌ Task {task_id} failed: {e}")
            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "processing_time": time.time() - start_time if 'start_time' in locals() else 0
            }

class AdvancedVoiceControls:
    """Advanced voice parameter controls for fine-tuning"""
    
    @staticmethod
    def adjust_pitch(audio: np.ndarray, sr: int, pitch_shift: float) -> np.ndarray:
        """
        Adjust pitch of audio
        
        Args:
            audio: Audio signal
            sr: Sample rate
            pitch_shift: Pitch shift in semitones (positive = higher, negative = lower)
        """
        try:
            if abs(pitch_shift) < 0.01:  # No change needed
                return audio
            
            # Use librosa for pitch shifting
            shifted_audio = librosa.effects.pitch_shift(
                y=audio,
                sr=sr,
                n_steps=pitch_shift,
                bins_per_octave=12
            )
            
            return shifted_audio.astype(audio.dtype)
            
        except Exception as e:
            logger.error(f"❌ Pitch adjustment failed: {e}")
            return audio
    
    @staticmethod
    def adjust_tempo(audio: np.ndarray, tempo_factor: float) -> np.ndarray:
        """
        Adjust tempo without affecting pitch
        
        Args:
            audio: Audio signal
            tempo_factor: Tempo multiplier (1.0 = normal, 1.5 = 50% faster, 0.5 = 50% slower)
        """
        try:
            if abs(tempo_factor - 1.0) < 0.01:  # No change needed
                return audio
            
            # Use librosa for time stretching
            stretched_audio = librosa.effects.time_stretch(
                y=audio,
                rate=tempo_factor
            )
            
            return stretched_audio.astype(audio.dtype)
            
        except Exception as e:
            logger.error(f"❌ Tempo adjustment failed: {e}")
            return audio
    
    @staticmethod
    def add_emotional_emphasis(
        audio: np.ndarray, 
        sr: int, 
        emotion: str = "neutral",
        intensity: float = 0.5
    ) -> np.ndarray:
        """
        Add emotional characteristics to speech
        
        Args:
            audio: Audio signal
            sr: Sample rate
            emotion: Target emotion ("happy", "sad", "angry", "calm", "excited")
            intensity: Emotion intensity (0.0 to 1.0)
        """
        try:
            if emotion == "neutral" or intensity < 0.1:
                return audio
            
            # Define emotion parameters
            emotion_params = {
                "happy": {"pitch_shift": 2.0, "tempo_factor": 1.1, "energy_boost": 1.2},
                "sad": {"pitch_shift": -1.5, "tempo_factor": 0.9, "energy_boost": 0.8},
                "angry": {"pitch_shift": 1.0, "tempo_factor": 1.2, "energy_boost": 1.5},
                "calm": {"pitch_shift": -0.5, "tempo_factor": 0.95, "energy_boost": 0.9},
                "excited": {"pitch_shift": 3.0, "tempo_factor": 1.15, "energy_boost": 1.3}
            }
            
            if emotion not in emotion_params:
                logger.warning(f"⚠️ Unknown emotion: {emotion}")
                return audio
            
            params = emotion_params[emotion]
            
            # Apply transformations with intensity scaling
            modified_audio = audio.copy()
            
            # Pitch adjustment
            pitch_shift = params["pitch_shift"] * intensity
            if abs(pitch_shift) > 0.1:
                modified_audio = AdvancedVoiceControls.adjust_pitch(modified_audio, sr, pitch_shift)
            
            # Tempo adjustment
            tempo_factor = 1.0 + (params["tempo_factor"] - 1.0) * intensity
            if abs(tempo_factor - 1.0) > 0.05:
                modified_audio = AdvancedVoiceControls.adjust_tempo(modified_audio, tempo_factor)
            
            # Energy/volume adjustment
            energy_factor = 1.0 + (params["energy_boost"] - 1.0) * intensity
            modified_audio = modified_audio * energy_factor
            
            # Ensure no clipping
            max_val = np.max(np.abs(modified_audio))
            if max_val > 1.0:
                modified_audio = modified_audio / max_val * 0.95
            
            return modified_audio.astype(audio.dtype)
            
        except Exception as e:
            logger.error(f"❌ Emotional emphasis failed: {e}")
            return audio
    
    @staticmethod
    def apply_voice_style(
        audio: np.ndarray,
        sr: int,
        style_params: Dict[str, float]
    ) -> np.ndarray:
        """
        Apply comprehensive voice styling
        
        Args:
            audio: Audio signal
            sr: Sample rate
            style_params: Dictionary with parameters:
                - pitch_shift: float (semitones)
                - tempo_factor: float (multiplier)
                - emotion: str
                - emotion_intensity: float (0-1)
                - reverb: float (0-1)
                - brightness: float (0-2, 1=normal)
        """
        try:
            modified_audio = audio.copy()
            
            # Apply pitch shift
            if "pitch_shift" in style_params:
                modified_audio = AdvancedVoiceControls.adjust_pitch(
                    modified_audio, sr, style_params["pitch_shift"]
                )
            
            # Apply tempo change
            if "tempo_factor" in style_params:
                modified_audio = AdvancedVoiceControls.adjust_tempo(
                    modified_audio, style_params["tempo_factor"]
                )
            
            # Apply emotional characteristics
            if "emotion" in style_params and "emotion_intensity" in style_params:
                modified_audio = AdvancedVoiceControls.add_emotional_emphasis(
                    modified_audio, sr, 
                    style_params["emotion"], 
                    style_params["emotion_intensity"]
                )
            
            # Apply brightness (EQ adjustment)
            if "brightness" in style_params:
                brightness = style_params["brightness"]
                if abs(brightness - 1.0) > 0.1:
                    # Simple high-frequency emphasis/de-emphasis
                    from scipy import signal
                    
                    if brightness > 1.0:
                        # Boost high frequencies
                        b, a = signal.butter(2, 0.3, 'high')
                        high_freq = signal.filtfilt(b, a, modified_audio)
                        boost_factor = (brightness - 1.0) * 0.3
                        modified_audio = modified_audio + high_freq * boost_factor
                    else:
                        # Reduce high frequencies
                        b, a = signal.butter(2, 0.7, 'low')
                        modified_audio = signal.filtfilt(b, a, modified_audio)
            
            # Apply reverb (simple delay-based)
            if "reverb" in style_params:
                reverb_amount = style_params["reverb"]
                if reverb_amount > 0.05:
                    delay_samples = int(0.05 * sr)  # 50ms delay
                    reverb_signal = np.zeros_like(modified_audio)
                    if len(modified_audio) > delay_samples:
                        reverb_signal[delay_samples:] = modified_audio[:-delay_samples] * reverb_amount * 0.3
                        modified_audio = modified_audio + reverb_signal
            
            # Normalize to prevent clipping
            max_val = np.max(np.abs(modified_audio))
            if max_val > 1.0:
                modified_audio = modified_audio / max_val * 0.95
            
            return modified_audio.astype(audio.dtype)
            
        except Exception as e:
            logger.error(f"❌ Voice styling failed: {e}")
            return audio

# Global instances
similarity_scorer = VoiceSimilarityScorer()
batch_processor = BatchVoiceProcessor()

# Helper functions for easy access
async def calculate_voice_similarity(reference_path: str, generated_path: str) -> Dict[str, float]:
    """Calculate similarity between reference and generated audio"""
    try:
        ref_audio, ref_sr = librosa.load(reference_path, sr=22050)
        gen_audio, gen_sr = librosa.load(generated_path, sr=22050)
        
        return similarity_scorer.calculate_similarity(ref_audio, gen_audio, ref_sr)
    except Exception as e:
        logger.error(f"❌ Similarity calculation failed: {e}")
        return {"error": str(e)}

async def process_voice_batch(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process multiple voice synthesis tasks"""
    return await batch_processor.process_batch(tasks)

def apply_advanced_voice_styling(audio_path: str, style_params: Dict[str, float]) -> str:
    """Apply advanced voice styling to audio file"""
    try:
        # Load audio
        audio, sr = librosa.load(audio_path, sr=22050)
        
        # Apply styling
        styled_audio = AdvancedVoiceControls.apply_voice_style(audio, sr, style_params)
        
        # Save to new file
        import tempfile
        fd, output_path = tempfile.mkstemp(prefix="styled-", suffix=".wav")
        os.close(fd)
        
        librosa.output.write_wav(output_path, styled_audio, sr)
        
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Voice styling failed: {e}")
        raise

logger.info("✅ Enhanced voice features module loaded")