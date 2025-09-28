from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import whisper

app = FastAPI(title="Whisper Large v3 Transcription API")
model = whisper.load_model("large-v3", device="cuda", language=None)

class TranscriptionResult(BaseModel):
    text: str

@app.post("/transcribe", response_model=TranscriptionResult)
async def transcribe(audio_file: UploadFile = File(...)):
    # Save uploaded file to disk
    file_path = f"/tmp/{audio_file.filename}"
    with open(file_path, "wb") as f:
        f.write(await audio_file.read())

    # Run Whisper inference
    result = model.transcribe(file_path, fp16=True)
    return TranscriptionResult(text=result["text"])
