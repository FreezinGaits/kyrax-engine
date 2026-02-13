
try:
    import kyrax_core
    print(f"kyrax_core location: {kyrax_core.__file__}")
except ImportError:
    print("kyrax_core not found")

import sys
print(f"sys.path: {sys.path}")

try:
    import playwright
    print("✓ playwright imported")
    from playwright.sync_api import sync_playwright
    print("✓ playwright.sync_api imported")
except ImportError as e:
    print(f"❌ playwright import failed: {e}")

try:
    import whisper
    print("✓ whisper imported")
except ImportError as e:
    print(f"❌ whisper import failed: {e}")

try:
    from kyrax_core.adapters.voice_adapter import WhisperVoiceAdapter
    print("✓ WhisperVoiceAdapter imported")
except ImportError as e:
    print(f"❌ WhisperVoiceAdapter import failed: {e}")
    import traceback
    traceback.print_exc()

try:
    import sounddevice
    print("✓ sounddevice imported")
except ImportError as e:
    print(f"❌ sounddevice import failed: {e}")
