# kyrax_core/adapters/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
import datetime


@dataclass
class AdapterOutput:
    """
    Standard output from any input adapter.
    - text: plain, cleaned, UTF-8 text (no commands, no intents)
    - source: "voice" | "text" | "api" | custom
    - meta: adapter-specific metadata (sample rate, file, duration, etc.)
    - timestamp: ISO timestamp when text was produced
    """
    text: str
    source: str
    meta: Optional[Dict[str, Any]] = None
    timestamp: str = datetime.datetime.utcnow().isoformat() + "Z"


class InputAdapter(ABC):
    """
    Adapter contract: listen() returns AdapterOutput synchronously.
    Adapters MUST NOT interpret language or create Command objects.
    """

    @abstractmethod
    def listen(self) -> AdapterOutput:
        """Blocking call that returns AdapterOutput."""
        raise NotImplementedError
