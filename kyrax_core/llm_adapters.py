# kyrax_core/llm_adapters.py
"""
LLM Adapter abstraction layer for KYRAX.

All LLM usage should go through adapters here for consistency and easy swapping.
"""
import json
import os
from typing import Callable, Any, Optional

# Gemini adapter (primary LLM for KYRAX)
def gemini_llm_callable(model: Optional[str] = None) -> Optional[Callable[[str, int], str]]:
    """
    Create a Gemini LLM callable: llm(prompt, max_tokens) -> str
    
    Requires GEMINI_API_KEY environment variable.
    Returns None if Gemini is not available.
    """
    try:
        from kyrax_core.llm.gemini_client import GeminiClient
    except ImportError: 
        return None
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    
    try:
        client = GeminiClient(model=model)
    except Exception:
        return None
    
    def llm(prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        return client.complete(prompt, max_tokens=max_tokens, temperature=temperature)
    
    return llm

# OpenAI adapter (optional alternative)
def openai_llm_callable(api_key: Optional[str] = None) -> Optional[Callable[[str, int], str]]:
    """
    Create an OpenAI LLM callable: llm(prompt, max_tokens) -> str
    
    Args:
        api_key: OpenAI API key (or use OPENAI_API_KEY env var)
    Returns None if OpenAI is not available.
    """
    try:
        import openai
    except ImportError:
        return None
    
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    
    openai.api_key = api_key
    
    def llm(prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        try:
            resp = openai.ChatCompletion.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e
    
    return llm

# Deterministic stub for testing/fallback
def deterministic_llm_stub():
    """
    Returns a stub LLM that always returns a clarification request.
    Useful for testing or when no LLM is available.
    """
    def llm(prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
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

# Convenience function: get best available LLM
def get_llm_callable(prefer: str = "gemini", model: Optional[str] = None) -> Optional[Callable[[str, int], str]]:
    """
    Get the best available LLM callable.
    
    Args:
        prefer: "gemini" or "openai"
        model: Optional model name (for Gemini)
    
    Returns:
        LLM callable or None if none available
    """
    from kyrax_core.llm.gemini_client import GeminiClient
    if prefer == "gemini":
        result = gemini_llm_callable(model=model)
        if result:
            return result
        return openai_llm_callable()
    else:
        result = openai_llm_callable()
        if result:
            return result
        return gemini_llm_callable(model=model)
