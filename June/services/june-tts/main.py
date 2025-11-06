"""
CosyVoice2 FastAPI TTS Microservice
Provides RESTful endpoints for text-to-speech synthesis
"""

import sys
import io
import base64
import argparse
from typing import Optional, List
from pathlib import Path

import torch
import torchaudio
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# Add third_party/Matcha-TTS to path
sys.path.append('third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

# ============== Request/Response Models ==============

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    stream: bool = Field(default=False, description="Enable streaming output")

class ZeroShotRequest(TTSRequest):
    prompt_text: str = Field(..., description="Reference text for voice cloning")
    zero_shot_spk_id: Optional[str] = Field(None, description="Pre-saved zero-shot speaker ID")

class SFTRequest(TTSRequest):
    speaker: str = Field("中文女", description="Speaker name from available SFT speakers")

class CrossLingualRequest(TTSRequest):
    pass

class InstructRequest(TTSRequest):
    instruct_text: str = Field(..., description="Instruction for voice style, e.g., 'use Sichuan dialect'")

class VoiceConversionRequest(BaseModel):
    stream: bool = Field(default=False, description="Enable streaming output")

class TTSResponse(BaseModel):
    message: str
    audio_base64: Optional[str] = None
    sample_rate: int
    duration_seconds: Optional[float] = None

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    available_speakers: List[str]

class SpeakerInfo(BaseModel):
    speaker_id: str
    status: str

# ============== Initialize FastAPI App ==============

app = FastAPI(
    title="CosyVoice2 TTS API",
    description="Multi-lingual Text-to-Speech API using CosyVoice2-0.5B",
    version="1.0.0"
)

# Global model instance
cosyvoice_model = None

# ============== Helper Functions ==============

def audio_to_base64(audio_tensor: torch.Tensor, sample_rate: int) -> str:
    """Convert audio tensor to base64 encoded WAV"""
    buffer = io.BytesIO()
    torchaudio.save(buffer, audio_tensor, sample_rate, format="wav")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')

def load_audio_from_upload(audio_file: UploadFile, target_sr: int = 16000) -> torch.Tensor:
    """Load audio from uploaded file"""
    # Save uploaded file temporarily
    temp_path = f"/tmp/{audio_file.filename}"
    with open(temp_path, "wb") as f:
        f.write(audio_file.file.read())
    
    # Load and resample if needed
    audio, sr = torchaudio.load(temp_path)
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(sr, target_sr)
        audio = resampler(audio)
    
    return audio

# ============== API Endpoints ==============

@app.on_event("startup")
async def startup_event():
    """Initialize the model on startup"""
    global cosyvoice_model
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_dir', 
                       type=str, 
                       default='pretrained_models/CosyVoice2-0.5B',
                       help='Path to model directory')
    args, _ = parser.parse_known_args()
    
    print(f"Loading CosyVoice2 model from {args.model_dir}...")
    cosyvoice_model = CosyVoice2(
        args.model_dir,
        load_jit=False,
        load_trt=False,
        load_vllm=False,
        fp16=True  # Enable FP16 for better performance
    )
    print("Model loaded successfully!")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy" if cosyvoice_model is not None else "model_not_loaded",
        "model_loaded": cosyvoice_model is not None,
        "available_speakers": cosyvoice_model.list_available_spks() if cosyvoice_model else []
    }

@app.get("/speakers")
async def list_speakers():
    """List available SFT speakers"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {
        "speakers": cosyvoice_model.list_available_spks(),
        "count": len(cosyvoice_model.list_available_spks())
    }

@app.post("/tts/zero-shot")
async def zero_shot_tts(
    text: str = Form(...),
    prompt_text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    zero_shot_spk_id: Optional[str] = Form(None),
    stream: bool = Form(False)
):
    """
    Zero-shot voice cloning TTS
    
    - Upload a reference audio file with prompt text
    - The model will clone the voice and synthesize the target text
    - Optionally use a pre-saved speaker ID
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load prompt audio
        if not zero_shot_spk_id:
            prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        else:
            prompt_speech_16k = torch.tensor([])  # Empty tensor when using saved spk
        
        # Generate audio
        audio_chunks = []
        for i, output in enumerate(cosyvoice_model.inference_zero_shot(
            text, 
            prompt_text if not zero_shot_spk_id else '',
            prompt_speech_16k if not zero_shot_spk_id else '',
            zero_shot_spk_id=zero_shot_spk_id,
            stream=stream
        )):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate all chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Convert to base64
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Zero-shot TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/zero-shot/save-speaker")
async def save_zero_shot_speaker(
    speaker_id: str = Form(...),
    prompt_text: str = Form(...),
    prompt_audio: UploadFile = File(...)
):
    """
    Save a zero-shot speaker for future use
    
    - This allows you to reuse a voice without uploading the audio each time
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load prompt audio
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        # Add speaker
        success = cosyvoice_model.add_zero_shot_spk(
            prompt_text, 
            prompt_speech_16k, 
            speaker_id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to save speaker")
        
        # Save speaker info
        cosyvoice_model.save_spkinfo()
        
        return {
            "speaker_id": speaker_id,
            "status": "saved successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save speaker: {str(e)}")

@app.post("/tts/sft")
async def sft_tts(
    text: str = Form(...),
    speaker: str = Form("中文女"),
    stream: bool = Form(False)
):
    """
    Supervised Fine-Tuned (SFT) TTS with preset speakers
    
    - Use pre-trained speaker voices
    - Get list of available speakers from /speakers endpoint
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Generate audio
        audio_chunks = []
        for i, output in enumerate(cosyvoice_model.inference_sft(
            text,
            speaker,
            stream=stream
        )):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate all chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Convert to base64
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "SFT TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/cross-lingual")
async def cross_lingual_tts(
    text: str = Form(..., description="Text with language tags like <|en|>Hello"),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(False)
):
    """
    Cross-lingual TTS - speak text in different language with same voice
    
    - Supports language tags: <|zh|> <|en|> <|jp|> <|yue|> <|ko|>
    - Upload reference audio to clone voice
    - Text can be in different language than reference
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load prompt audio
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        # Generate audio
        audio_chunks = []
        for i, output in enumerate(cosyvoice_model.inference_cross_lingual(
            text,
            prompt_speech_16k,
            stream=stream
        )):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate all chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Convert to base64
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Cross-lingual TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/instruct")
async def instruct_tts(
    text: str = Form(...),
    instruct_text: str = Form(..., description="e.g., 'use Sichuan dialect', 'speak with emotion'"),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(False)
):
    """
    Instruct-based TTS with style control
    
    - Control voice style, emotion, dialect through instructions
    - Supports fine-grained control with tags like [laughter] [breath]
    - Example instructions: "use Sichuan dialect", "speak cheerfully"
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load prompt audio
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        # Generate audio
        audio_chunks = []
        for i, output in enumerate(cosyvoice_model.inference_instruct2(
            text,
            instruct_text,
            prompt_speech_16k,
            stream=stream
        )):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate all chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Convert to base64
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Instruct TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/voice-conversion")
async def voice_conversion(
    source_audio: UploadFile = File(..., description="Audio to convert"),
    prompt_audio: UploadFile = File(..., description="Target voice reference"),
    stream: bool = Form(False)
):
    """
    Voice conversion - convert source audio to target voice
    
    - Upload source audio and target voice reference
    - The model will convert source audio to match target voice
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load audios
        source_speech_16k = load_audio_from_upload(source_audio, 16000)
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        # Generate audio
        audio_chunks = []
        for i, output in enumerate(cosyvoice_model.inference_vc(
            source_speech_16k,
            prompt_speech_16k,
            stream=stream
        )):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate all chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Convert to base64
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Voice conversion completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice conversion failed: {str(e)}")

# ============== Main ==============

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50000, help='Server port')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Server host')
    parser.add_argument('--model_dir', type=str, 
                       default='pretrained_models/CosyVoice2-0.5B',
                       help='Path to model directory')
    
    args = parser.parse_args()
    
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port,
        log_level="info"
    )