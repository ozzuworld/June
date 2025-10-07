"""
Utility functions for file handling.

Currently unused in the simplified API. Left here for future extensions.
"""

from fastapi import UploadFile, HTTPException, status
from ..core.config import settings


async def validate_audio_file(file: UploadFile) -> None:
    """
    Validate an uploaded audio file against size and extension constraints.

    Raises an HTTPException if the file is invalid.
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in settings.allowed_audio_formats:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported audio format")
    if file.size is not None and file.size > settings.max_file_size:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")