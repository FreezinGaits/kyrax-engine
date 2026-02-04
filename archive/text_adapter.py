# kyrax_core/adapters/text_adapter.py
from kyrax_core.adapters.base import InputAdapter, AdapterOutput


class CLITextAdapter(InputAdapter):
    """
    Simple CLI text adapter. `listen()` blocks waiting for user input.
    """

    def __init__(self, prompt: str = "You: "):
        self.prompt = prompt

    def listen(self) -> AdapterOutput:
        raw = input(self.prompt).strip()
        return AdapterOutput(text=raw, source="text", meta={"via": "cli"})
