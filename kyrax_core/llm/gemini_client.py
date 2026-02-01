# kyrax_core/llm/gemini_client.py
from google import genai
import os
import logging
from typing import List
from google.genai.errors import ClientError

log = logging.getLogger(__name__)
def _normalize_model_name(name: str) -> str:
    # google.genai REQUIRES full resource name
    if name.startswith("models/"):
        return name
    return f"models/{name}"

class GeminiClient:
    """
    Thin wrapper around google.genai.Client with model fallback + friendly errors.

    Usage:
      GEMINI_API_KEY must be set in env.
      Optionally set GEMINI_MODEL to prefer a specific model name.
    """

    # sensible fallback candidates (try in order)
    DEFAULT_MODEL_CANDIDATES = [
        # "models/gemini-pro-latest",
        "models/gemini-flash-latest",
        # "models/gemini-2.5-flash",
    ]
    

    def __init__(self, model: str | None = None):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Get it from https://aistudio.google.com/app/apikey"
            )

        self.client = genai.Client(api_key=api_key)

        # ✅ ENV VAR HAS ABSOLUTE PRIORITY
        env_model = os.getenv("GEMINI_MODEL")

        candidates = []

        if env_model:
            candidates.append(env_model)

        if model:
            candidates.append(model)

        candidates.extend(self.DEFAULT_MODEL_CANDIDATES)

        # de-duplicate while preserving order
        seen = set()
        self.model_candidates = []
        for m in candidates:
            if not m.startswith("models/"):
                m = f"models/{m}"
            if m not in seen:
                seen.add(m)
                self.model_candidates.append(m)

        log.info("GeminiClient model candidates: %s", self.model_candidates)



    def _extract_text_from_response(self, response) -> str:
        # Structured response: response.candidates[0].content.parts -> list of parts w/ text
        if not getattr(response, "candidates", None):
            return ""
        cand = response.candidates[0]
        # content may be in cand.content.parts (list) where each part has .text
        parts = getattr(cand, "content", None)
        if parts is None:
            return ""
        # parts may be an object with .parts attr
        part_list = getattr(parts, "parts", parts)  # try both
        texts = []
        for p in part_list:
            t = getattr(p, "text", None)
            if t:
                texts.append(t)
        return "".join(texts)

    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        self._cache = getattr(self, "_cache", {})
        key = (prompt, max_tokens, temperature)
        if key in self._cache:
            return self._cache[key]

        errors = []

        for model in self.model_candidates:
            try:
                log.info("GeminiClient: trying model %s", model)

                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "temperature": temperature,
                        "max_output_tokens": max_tokens,
                    },
                )

                if not response.candidates:
                    raise RuntimeError("No candidates returned")

                parts = response.candidates[0].content.parts
                if not parts:
                  log.warning("Gemini returned empty content; treating as no-op")
                  continue   # try next model or fallback

                
                result = "".join(p.text for p in parts if hasattr(p, "text"))
                self._cache[key] = result
                return result

                

            except Exception as e:
                log.warning("GeminiClient: model %s failed with %s", model, e)
                errors.append((model, str(e)))

        raise RuntimeError(
            "Gemini: no usable model found. Tried models:\n"
            + "\n".join(f"- {m}: {err}" for m, err in errors)
        )

