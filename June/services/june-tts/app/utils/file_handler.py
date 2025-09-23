from fastapi import HTTPException, status, UploadFile
from app.core.config import settings
import magic

async def validate_audio_file(file: UploadFile):
    """Validate uploaded audio file"""
    
    # Check file size
    if file.size and file.size > settings.max_file_size:
        raise ValueError(f"File too large. Maximum size: {settings.max_file_size // 1024 // 1024}MB")
    
    # Check file extension
    if not file.filename:
        raise ValueError("Filename is required")
    
    extension = file.filename.split('.')[-1].lower()
    if extension not in settings.allowed_audio_formats:
        raise ValueError(f"Unsupported format. Allowed: {', '.join(settings.allowed_audio_formats)}")
    
    # Reset file pointer
    await file.seek(0)
    
    # Check file content (basic validation)
    file_content = await file.read(1024)  # Read first 1KB
    await file.seek(0)  # Reset pointer
    
    # Basic audio format validation
    if len(file_content) < 100:
        raise ValueError("File appears to be too small to be a valid audio file")
    
    return True
