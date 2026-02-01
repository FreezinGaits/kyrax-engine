import whisper

model = whisper.load_model("base", download_root="./models")

# Load audio
audio = whisper.load_audio("audio.m4a")
audio = whisper.pad_or_trim(audio)

# Make log-Mel spectrogram
mel = whisper.log_mel_spectrogram(audio).to(model.device)

# Detect language
_, probs = model.detect_language(mel)
print(f"Detected language: {max(probs, key=probs.get)}")

# Decode/Transcribe with options
options = whisper.DecodingOptions(language="en", task="transcribe")
result = whisper.decode(model, mel, options)

print(result.text)