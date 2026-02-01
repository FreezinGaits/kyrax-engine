# kyrax_core/command.py
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
import json


@dataclass
class Command:
    """
    KYRAX internal command representation.
    Execution-first, AI-agnostic, and serializable.
    """
    intent: str                     # e.g., "send_message", "open_app"
    domain: str                     # e.g., "application", "os", "iot", "web", "system"
    entities: Dict[str, Any] = field(default_factory=dict)  # parameters needed to perform the action
    # default_factory=dict ensures that each new Command object gets its own fresh empty dictionary.

    confidence: float = 1.0         # 0.0 - 1.0
    source: str = "text"            # "voice", "text", "api"
    context_id: Optional[str] = None  # short id to link to context/memory
    meta: Dict[str, Any] = field(default_factory=dict)  # any transport metadata

    def is_valid(self) -> bool:
        """Basic sanity checks before dispatch."""
        if not self.intent or not isinstance(self.intent, str):
            return False
        if not self.domain or not isinstance(self.domain, str):
            return False
        if not isinstance(self.entities, dict):
            return False
        if not (0.0 <= self.confidence <= 1.0):
            return False
        return True

    def to_json(self) -> str:
        """Serialize to stable JSON (useful for logging / storage)."""
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        # ensure_ascii=False → Keeps Unicode characters intact instead of escaping them.
        # Example: "café" stays "café" instead of "caf\u00e9".
        # sort_keys=True → Ensures dictionary keys are sorted alphabetically in the JSON output.
        # This makes logs and storage consistent and predictable.

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain Python dict representation (useful for printing/tests)."""
        return asdict(self)

    @staticmethod
    def from_json(payload: str) -> "Command":
        """Deserialize from JSON string."""
        data = json.loads(payload)
        return Command(
            intent=data.get("intent", ""),
            domain=data.get("domain", ""),
            entities=data.get("entities", {}),
            confidence=float(data.get("confidence", 1.0)),
            source=data.get("source", "text"),
            context_id=data.get("context_id"),
            meta=data.get("meta", {}),
        )

    def get(self, key: str, default=None):
        return self.entities.get(key, default)
    # Looks up a value in the entities dictionary by key.
    # If the key doesn’t exist, returns the default instead of raising an error.

    def __repr__(self):
        return f"Command(intent={self.intent!r}, domain={self.domain!r}, entities={self.entities!r}, confidence={self.confidence:.2f}, source={self.source!r})"
