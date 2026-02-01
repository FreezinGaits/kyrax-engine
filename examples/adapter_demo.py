# examples/adapter_demo.py
"""
Demo that shows:
- CLI text adapter
- Voice adapter from file (use a short WAV/MP3 file)
- (Optional) mic recording if sounddevice installed

Run:
python -m examples.adapter_demo
"""
from kyrax_core.adapters.text_adapter import CLITextAdapter
from kyrax_core.adapters.voice_adapter import WhisperVoiceAdapter
from kyrax_core.adapters.base import AdapterOutput

def demo_cli_text():
    cli = CLITextAdapter()
    out = cli.listen()
    print("AdapterOutput:", out)

def demo_voice_file(path):
    va = WhisperVoiceAdapter(model_name="base")
    out = va.listen(mode="file", audio_path=path)
    print("Voice AdapterOutput:", out)

def demo_voice_mic(seconds=3):
    va = WhisperVoiceAdapter(model_name="tiny")
    out = va.listen(mode="mic", record_seconds=seconds)
    print("Voice (mic) AdapterOutput:", out)

if __name__ == "__main__":
    print("1) CLI text demo")
    demo_cli_text()
    # replace with a real audio file path you have for testing:
    # print("\n2) Voice file demo (replace path)")
    # demo_voice_file("samples/hello.wav")
    # print("\n3) Voice mic demo (requires sounddevice)")
    # demo_voice_mic(3)
