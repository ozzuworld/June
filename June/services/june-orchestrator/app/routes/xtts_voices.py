#!/usr/bin/env python3
"""
XTTS Voice Management Endpoints

Manages voice cloning and PostgreSQL voice storage.
Replaces CosyVoice2 language-based system.
"""
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import List

from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/voices")
async def list_voices():
    """
    Get list of all available XTTS voices from PostgreSQL
    
    Returns:
        List of voices with id, name, size, timestamps
    """
    try:
        voices = await tts_service.list_voices()
        
        return {
            "status": "success",
            "engine": "xtts",
            "model": "XTTS-v2",
            "storage": "postgresql",
            "voices": voices,
            "count": len(voices),
            "note": "XTTS uses voice cloning from reference audio stored in PostgreSQL"
        }
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voices/{voice_id}")
async def get_voice_info(voice_id: str):
    """
    Get detailed information about a specific voice
    
    Args:
        voice_id: Unique voice identifier
        
    Returns:
        Voice details including size, timestamps, and status
    """
    try:
        voice_info = await tts_service.get_voice_info(voice_id)
        
        if not voice_info:
            raise HTTPException(
                status_code=404,
                detail=f"Voice '{voice_id}' not found"
            )
        
        return {
            "status": "success",
            **voice_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get voice info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/voices/clone")
async def clone_voice(
    voice_id: str = Form(...),
    voice_name: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Clone a voice from uploaded audio and store in PostgreSQL
    
    Requirements:
    - Audio: 6-10 seconds recommended (3-60s accepted)
    - Format: WAV, MP3, or FLAC
    - Sample rate: 22kHz minimum
    - Quality: Clean speech, no background noise
    
    Args:
        voice_id: Unique identifier (e.g., "june", "assistant_1")
        voice_name: Human-readable name (e.g., "June AI Assistant")
        file: Audio file upload
        
    Returns:
        Voice cloning result with embedding info
    """
    try:
        # Validate file type
        if not file.filename.endswith(('.wav', '.mp3', '.flac')):
            raise HTTPException(
                status_code=400,
                detail="Only WAV, MP3, and FLAC audio files are supported"
            )
        
        # Save temp file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            # Clone voice via TTS service
            result = await tts_service.clone_voice(
                voice_id=voice_id,
                voice_name=voice_name,
                audio_file_path=tmp_path
            )
            
            if result.get("status") == "error":
                raise HTTPException(
                    status_code=500,
                    detail=result.get("detail", "Voice cloning failed")
                )
            
            return result
            
        finally:
            # Cleanup temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """
    Delete a voice from PostgreSQL database
    
    Args:
        voice_id: Voice to delete
        
    Returns:
        Deletion confirmation
    """
    try:
        # Check if voice exists first
        voice_info = await tts_service.get_voice_info(voice_id)
        if not voice_info:
            raise HTTPException(
                status_code=404,
                detail=f"Voice '{voice_id}' not found"
            )
        
        # Delete voice
        success = await tts_service.delete_voice(voice_id)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete voice '{voice_id}'"
            )
        
        return {
            "status": "success",
            "message": f"Voice '{voice_id}' deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voices/info")
async def get_system_info():
    """
    Get information about XTTS voice system
    
    Returns:
        System capabilities and configuration
    """
    return {
        "status": "success",
        "engine": "XTTS-v2",
        "version": "2.0",
        "architecture": "Voice cloning with speaker embeddings",
        "features": {
            "voice_cloning": "Clone any voice from 3-60 second audio sample",
            "multilingual": "Supports multiple languages with single voice",
            "streaming": "Real-time audio streaming with low latency",
            "storage": "PostgreSQL database for voice management"
        },
        "optimal_audio": {
            "duration": "6-10 seconds",
            "format": "WAV, MP3, or FLAC",
            "sample_rate": "22kHz minimum",
            "quality": "Clean speech, no background noise"
        },
        "storage_backend": "PostgreSQL",
        "note": "XTTS uses voice cloning instead of predefined speakers"
    }