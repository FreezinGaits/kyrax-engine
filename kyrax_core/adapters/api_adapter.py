# kyrax_core/adapters/api_adapter.py
"""
Lightweight FastAPI adapter exposing two endpoints:
- POST /text  -> accepts JSON {"text": "..."} and returns AdapterOutput-like JSON
- POST /transcribe -> accepts multipart file upload "file" (audio) and returns transcribed text

Run with:
uvicorn kyrax_core.adapters.api_adapter:app --reload --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import shutil
import tempfile
import os

from .base import AdapterOutput
from .voice_adapter import WhisperVoiceAdapter

app = FastAPI(title="KYRAX Input Adapter API")

# instantiate a shared voice adapter (model choice configurable)
# NOTE: model will be loaded on first use (lazy)
VOICE_ADAPTER = WhisperVoiceAdapter(model_name="base")


class TextIn(BaseModel):
    text: str


@app.post("/text")
def post_text(payload: TextIn) -> Dict[str, Any]:
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    out = AdapterOutput(text=payload.text.strip(), source="api_text", meta={"via": "fastapi"})
    return out.__dict__


@app.post("/transcribe")
def upload_audio(file: UploadFile = File(...)):
    # save to temp file and forward to voice adapter
    suffix = os.path.splitext(file.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

    try:
        out = VOICE_ADAPTER.transcribe_file(tmp_path)
        # convert dataclass to dict
        return out.__dict__
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
