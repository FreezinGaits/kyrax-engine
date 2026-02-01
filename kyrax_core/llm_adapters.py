# kyrax_core/llm_adapters.py
import json
from typing import Callable, Any

# Example OpenAI adapter (sync). Replace key/source as needed.
# pip install openai
def openai_llm_callable(api_key: str):
    import openai
    openai.api_key = api_key

    def llm(prompt: str, max_tokens: int = 512) -> str:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",           # replace with model you have access to
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0
        )
        return resp.choices[0].message.content
    return llm

# If you don't want to hit OpenAI, use a simple stub that returns deterministic proposal JSON:
def deterministic_llm_stub():
    def llm(prompt: str, max_tokens: int = 512) -> str:
        # Return minimal JSON consistent with AIReasoner expectation
        payload = [{
            "explanation": "Ask clarify",
            "score": 0.5,
            "steps": [
                {"intent": "ask_clarify", "entities": {"question": "I couldn't parse that. Which contact?"}, "domain":"system", "confidence":0.5}
            ]
        }]
        return json.dumps(payload)
    return llm
