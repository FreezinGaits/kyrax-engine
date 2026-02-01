# kyrax_core/nlu/llm_nlu.py
from typing import Dict, Any, Optional
import json
import re

from kyrax_core.llm.gemini_client import GeminiClient

# small safe prompt template to ask Gemini to return strict JSON
_PROMPT_TEMPLATE = """
You are a strict JSON extractor for a personal assistant.

Return ONLY valid JSON.
Do NOT include explanations or markdown.

JSON schema:
{{
  "intent": "send_message | open_app | turn_on | turn_off | play_music | search_web | take_note | null",
  "entities": {{
    "contact": string | null,
    "text": string | null,
    "app": string | null,
    "device": string | null,
    "query": string | null
  }},
  "confidence": number
}}

Rules:
- Do NOT hallucinate contacts
- Preserve user text exactly
- Use null when unsure
- confidence must be between 0 and 1

User utterance:
\"\"\"{text}\"\"\"
"""



class LLMNLU:
    def __init__(self, gemini_client: Optional[GeminiClient] = None, model: str = "gemini-pro"):
        self.client = gemini_client or GeminiClient(model=model)

    def analyze(self, text: str) -> Dict[str, Any]:
        prompt = _PROMPT_TEMPLATE.format(text=text)
        raw = self.client.complete(prompt, max_tokens=512, temperature=0.0)

        # try to extract JSON portion
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {"intent": None, "entities": {}, "confidence": 0.0, "source": "gemini_raw"}
        try:
            data = json.loads(m.group(0))
            # normalize shapes -> ensure keys exist
            data.setdefault("entities", data.get("entities") or {})
            data["confidence"] = float(data.get("confidence") or 0.0)
            data["source"] = "gemini"
            return data
        except Exception:
            return {"intent": None, "entities": {}, "confidence": 0.0, "source": "gemini_parse_error"}
