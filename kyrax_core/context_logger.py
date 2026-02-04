# kyrax_core/context_logger.py
from collections import deque
from typing import Optional, Dict, Any
import time
import threading
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kyrax_core.command import Command

_PRONOUNS = {"him", "her", "them", "it", "that", "this", "they", "he", "she", "itself", "himself", "herself", "previous", "last", "earlier", "recent", "again", "previous contact", "previously"}

def _clean_contact_str(s: str) -> str:
    """
    Remove common speech prefixes like 'my friend', 'my', 'friend', 'the', 'a', and trailing words like 'again'.
    Keep a normalized title-cased name (best-effort).
    """
    if not s:
        return s
    ss = s.strip()
    # remove repeated noise at beginning
    ss = re.sub(r'^(my\s+friend\s+|my\s+|friend\s+|the\s+|a\s+)', '', ss, flags=re.I).strip()
    # remove trailing conversational tokens
    ss = re.sub(r'\b(again|please|now|earlier|previous|previously)\b', '', ss, flags=re.I).strip()
    # collapse multiple spaces
    ss = re.sub(r'\s+', ' ', ss)
    # title case as final normalization
    return " ".join([p.capitalize() for p in ss.split()])

class ContextLogger:
    def __init__(self, max_entries: int = 50, ttl_seconds: int = 600):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store = deque()  # each item: (ts, record_dict)

    def _trim(self):
        now = time.time()
        while self._store and (now - self._store[0][0] > self.ttl):
            self._store.popleft()
        while len(self._store) > self.max_entries:
            self._store.popleft()

    def update_from_command(self, cmd: "Command"):
        rec = {
            "last_intent": getattr(cmd, "intent", None),
            "last_app": cmd.entities.get("app") if isinstance(cmd.entities, dict) else None,
            "last_contact": cmd.entities.get("contact") if isinstance(cmd.entities, dict) else None,
            "last_device": cmd.entities.get("device") if isinstance(cmd.entities, dict) else None,
            "last_text": cmd.entities.get("text") if isinstance(cmd.entities, dict) else None,
            "timestamp": time.time()
        }
        with self._lock:
            self._store.append((time.time(), rec))
            self._trim()

    def get_most_recent(self, key: str) -> Optional[Any]:
        with self._lock:
            now = time.time()
            for ts, rec in reversed(self._store):
                if (now - ts) > self.ttl:
                    continue
                val = rec.get(key)
                if val not in (None, "", []):
                    return val
        return None

    def resolve_pronoun(self, token: str) -> Optional[Any]:
        if not token:
            return None
        t = str(token).lower().strip()
        if t not in _PRONOUNS:
            return None
        for k in ("last_contact", "last_device", "last_app", "last_text"):
            v = self.get_most_recent(k)
            if v:
                return v
        return None

    def _clean_contact_str(self, s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        s = str(s).strip()
        # remove common noisy prefixes/suffixes like "my friend", "again", "please", "the", "previous"
        s = re.sub(r'^(my\s+friend\s+|my\s+pal\s+|the\s+)', '', s, flags=re.I)
        s = re.sub(r'\b(again|please|previous contact|previous|last)\b', '', s, flags=re.I)
        s = re.sub(r'\s+', ' ', s).strip()
        # Titlecase name-like tokens (keep numbers as-is)
        if re.search(r'[A-Za-z]', s):
            return " ".join([p.capitalize() for p in s.split()])
        return s

    # inside class ContextLogger:
    def fill_missing_entities(self, entities: Dict[str, Any], required_keys: Optional[list] = None, raw_text: Optional[str] = None) -> Dict[str, Any]:
        """
        For each required_key missing or pronoun-like in entities, try to fill from context.
        Use raw_text to detect whether the user actually used a pronoun/previous-token.
        """
        out = dict(entities or {})
        required_keys = required_keys or []
        raw_text_l = (raw_text or "").lower()

        # helper to detect whether raw_text references previous/again/last/earlier
        def _mentions_previous(s: str) -> bool:
            if not s:
                return False
            return bool(re.search(r'\b(previous(?:\s+contact)?|last|earlier|again|one I messaged|one I texted|recent(?:ly)?)\b', s, re.I))

        for k in required_keys:
            val = out.get(k)
            # Clean present value if it's a conversational name (e.g., "my friend akshat")
            if isinstance(val, str) and val.strip():
                cleaned = _clean_contact_str(val)
                out[k] = cleaned
                continue

            # If missing OR empty, only fill if raw_text references previous or the value itself is pronoun-like
            if val is None or val in ("", []):
                if _mentions_previous(raw_text_l):
                    candidate = self.get_most_recent(f"last_{k}")
                    if candidate:
                        out[k] = candidate
                        continue

            # if present but is pronoun or conversational token, try resolve
            if isinstance(val, str) and val.lower().strip() in _PRONOUNS:
                resolved = self.resolve_pronoun(val)
                if resolved:
                    out[k] = resolved

        # Additionally, for any contact-like fields apply cleaning
        if "contact" in out and isinstance(out["contact"], str):
            out["contact"] = _clean_contact_str(out["contact"])

        return out

    def snapshot(self) -> list:
        with self._lock:
            return [rec.copy() for ts, rec in self._store]

    def get_all(self) -> Dict[str, Any]:
        """
        Return a flat dict of the most recent values for common context keys.
        Useful for passing to planners/reasoners that expect a simple context dict.
        
        Returns dict with keys like: last_contact, last_app, last_device, last_file, etc.
        """
        with self._lock:
            now = time.time()
            result = {}
            # Get most recent value for each key pattern
            for ts, rec in reversed(self._store):
                if (now - ts) > self.ttl:
                    break
                # Update result with any keys that aren't already set (most recent wins)
                for key, value in rec.items():
                    if key != "timestamp" and key not in result and value not in (None, "", []):
                        result[key] = value
            return result
