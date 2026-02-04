# kyrax_core/adapters/voice_adapter.py
import os
import tempfile
from typing import Optional, Dict, Any
from .base import InputAdapter, AdapterOutput

# Try to import whisper; if not available, we'll raise helpful errors at runtime
try:
    import whisper
    _HAS_WHISPER = True
except Exception:
    whisper = None
    _HAS_WHISPER = False

# Optional mic-recording dependency (lightweight). If not installed, mic mode will error with guidance.
try:
    import sounddevice as sd
    import soundfile as sf
    _HAS_SOUNDDEVICE = True
except Exception:
    sd = None
    sf = None
    _HAS_SOUNDDEVICE = False


class WhisperVoiceAdapter(InputAdapter):
    """
    Voice adapter using openai-whisper (local). Two modes:
      - from_file: transcribe an audio file path
      - from_mic: record from default microphone for `record_seconds` seconds and transcribe
    Notes:
      * You must have ffmpeg in PATH for whisper.load_audio / model.transcribe on many systems.
      * Model downloads happen the first time you call load_model(...); choose a small model for dev.
    """

    def __init__(self, model_name: str = "base", device: str = "cpu"):
        if not _HAS_WHISPER:
            raise RuntimeError(
                "Whisper package not found. Install with `pip install openai-whisper` or `faster-whisper`."
            )
        self.model_name = model_name
        self.device = device
        # load lazily only when needed (avoid long startup time)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            # This will download the model if not present (size depends on model_name)
            self._model = whisper.load_model(self.model_name, device=self.device)
        return self._model

    def transcribe_file(self, audio_path: str, language: Optional[str] = None) -> AdapterOutput:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # whisper transcribe returns dict with 'text' key
        result = self.model.transcribe(audio_path, language=language) if language else self.model.transcribe(audio_path)
        text = result.get("text", "").strip()
        meta: Dict[str, Any] = {
            "model": self.model_name,
            "audio_path": audio_path,
            "raw_result": {k: v for k, v in result.items() if k != "segments"},  # keep small
        }
        return AdapterOutput(text=text, source="voice", meta=meta)

    def record_and_transcribe(self, record_seconds: int = 4, samplerate: int = 44100, channels: int = 1) -> AdapterOutput:
        """
        Record a short clip from mic (blocking) and transcribe.
        Requires sounddevice and soundfile packages and a working system audio device.
        """
        if not _HAS_SOUNDDEVICE:
            raise RuntimeError(
                "sounddevice/soundfile not installed. Install with: pip install sounddevice soundfile\n"
                "Or use transcribe_file() with a pre-recorded audio file."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        print(f"[VoiceAdapter] Recording {record_seconds}s from default mic -> {tmp_path}")
        recording = sd.rec(int(record_seconds * samplerate), samplerate=samplerate, channels=channels, dtype="float32")
        sd.wait()
        sf.write(tmp_path, recording, samplerate)

        try:
            out = self.transcribe_file(tmp_path)
            out.meta = out.meta or {}
            out.meta.update({"record_seconds": record_seconds, "samplerate": samplerate})
            return out
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # The canonical listen() API (use mode: 'file' or 'mic')
    def listen(self, *, mode: str = "file", audio_path: Optional[str] = None, record_seconds: int = 4) -> AdapterOutput:
        if mode == "file":
            if not audio_path:
                raise ValueError("audio_path is required for mode='file'")
            return self.transcribe_file(audio_path)
        elif mode == "mic":
            return self.record_and_transcribe(record_seconds=record_seconds)
        else:
            raise ValueError("mode must be 'file' or 'mic'")
