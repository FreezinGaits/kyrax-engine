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
                if (now - ts) > self.ttl: # it ensures that we don’t accidentally return stale context. Even if _trim already removed expired entries, this is a second line of defense.
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

    #weaker method than the previous _clean_contact_str, as it only removes prefixes/suffixes if the entire string is a conversational token, otherwise it assumes the user is trying to provide a name and applies title-casing. This is to avoid over-cleaning cases where the user might say something like "my friend Akshat" and we want to preserve "Akshat" rather than stripping it down to nothing.:

    # def _clean_contact_str(self, s: Optional[str]) -> Optional[str]:
    #     if s is None:
    #         return None
    #     s = str(s).strip()
    #     # remove common noisy prefixes/suffixes like "my friend", "again", "please", "the", "previous"
    #     s = re.sub(r'^(my\s+friend\s+|my\s+pal\s+|the\s+)', '', s, flags=re.I)
    #     s = re.sub(r'\b(again|please|previous contact|previous|last)\b', '', s, flags=re.I)
    #     s = re.sub(r'\s+', ' ', s).strip()
    #     # Titlecase name-like tokens (keep numbers as-is)
    #     if re.search(r'[A-Za-z]', s):
    #         return " ".join([p.capitalize() for p in s.split()])
    #     return s

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
            return [rec.copy() for _, rec in self._store] # previously at the place of _ there was ts, but since timestamp is already stored in rec["timestamp"], we can just ignore the ts variable in the loop and use rec["timestamp"] when needed. This avoids confusion and keeps the code cleaner.

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
    # Suppose the store contains:

    # python
    # self._store = deque([
    #     (ts1, {"last_contact": "Akshat", "last_text": "hi"}),
    #     (ts2, {"last_contact": "Gautam", "last_app": "WhatsApp"})
    # ])
    # Calling get_all() returns:

    # python
    # {
    #     "last_contact": "Gautam",   # most recent
    #     "last_text": "hi",          # from earlier record
    #     "last_app": "WhatsApp"      # most recent
    # }












# Here’s a **detailed summary of all the functions and methods** in your `ContextLogger` module, including the helper functions:

# ---

# ## 🔹 Module-Level Helpers

# ### `_PRONOUNS`
# - A set of pronoun-like tokens (`"him"`, `"her"`, `"again"`, `"previous"`, etc.).
# - Used to detect when the user refers to something indirectly (e.g., “send it again”).

# ### `_clean_contact_str(s: str) -> str`
# - Cleans conversational noise from contact names.
# - Removes prefixes like `"my friend"`, `"the"`, `"a"`.
# - Removes trailing tokens like `"again"`, `"please"`, `"earlier"`.
# - Collapses spaces and applies title-casing.
# - Ensures `"my friend Akshat"` becomes `"Akshat"`.

# ---

# ## 🔹 Class: `ContextLogger`

# ### `__init__(self, max_entries=50, ttl_seconds=600)`
# - Initializes the logger.
# - `max_entries`: maximum number of records stored.
# - `ttl_seconds`: time-to-live for records (default 10 minutes).
# - Creates:
#   - `self._lock`: threading lock for safe concurrent access.
#   - `self._store`: deque to hold `(timestamp, record_dict)` entries.

# ---

# ### `_trim(self)`
# - Cleans up the store:
#   - Removes entries older than TTL.
#   - Removes oldest entries if the deque exceeds `max_entries`.
# - Ensures memory stays fresh and bounded.

# ---

# ### `update_from_command(self, cmd: "Command")`
# - Builds a record dictionary from a `Command` object:
#   - `last_intent`, `last_app`, `last_contact`, `last_device`, `last_text`.
#   - Adds a `timestamp`.
# - Appends `(time, record)` to the store under lock.
# - Calls `_trim` to clean up immediately.
# - Purpose: log each incoming command for later context resolution.

# ---

# ### `get_most_recent(self, key: str) -> Optional[Any]`
# - Retrieves the most recent non-empty value for a given key.
# - Iterates backwards through the store.
# - Skips expired entries (`(now - ts) > ttl`).
# - Returns the first valid value found.
# - Defensive check ensures stale context is never returned, even if `_trim` missed it.

# ---

# ### `resolve_pronoun(self, token: str) -> Optional[Any]`
# - Resolves pronoun-like tokens (`"him"`, `"her"`, `"again"`, etc.).
# - If the token is in `_PRONOUNS`, searches for the most recent value among:
#   - `last_contact`, `last_device`, `last_app`, `last_text`.
# - Returns the resolved entity if found.
# - Purpose: handle vague user input like “send it again” or “message him.”

# ---

# ### `fill_missing_entities(self, entities: Dict[str, Any], required_keys: Optional[list] = None, raw_text: Optional[str] = None) -> Dict[str, Any]`
# - Fills in missing or pronoun-like entities using context.
# - Steps:
#   1. Copies input entities.
#   2. Defines `_mentions_previous` → detects words like “previous,” “last,” “again” in raw text.
#   3. For each required key:
#      - If present and conversational, clean with `_clean_contact_str`.
#      - If missing, and raw text mentions previous, pull from context (`get_most_recent`).
#      - If present but pronoun-like, resolve with `resolve_pronoun`.
#   4. Cleans contact fields again at the end.
# - Purpose: make incomplete commands usable by filling gaps from history.

# ---

# ### `snapshot(self) -> list`
# - Returns a list of **copies** of all records in the store.
# - Uses lock for thread safety.
# - Ignores the outer timestamp since each record already has its own `"timestamp"`.
# - Purpose: debugging or inspection of full history.

# ---

# ### `get_all(self) -> Dict[str, Any]`
# - Returns a **flattened dict** of the most recent values for each key.
# - Iterates backwards through the store:
#   - Stops at expired entries.
#   - For each record, adds keys not already set.
#   - Most recent wins.
# - Ignores `"timestamp"` and empty values.
# - Example output:
#   ```python
#   {
#       "last_contact": "Gautam",
#       "last_text": "hi",
#       "last_app": "WhatsApp"
#   }
#   ```
# - Purpose: provide a simple “current context state” for planners/reasoners.

# ---

# ## ✅ Overall Summary
# - **Helpers**: `_clean_contact_str` and `_mentions_previous` normalize conversational input.  
# - **Storage**: `_store` holds a rolling history of command records.  
# - **Safety**: `_lock` ensures thread-safe access; `_trim` keeps memory bounded.  
# - **Retrieval**: `get_most_recent` and `get_all` fetch context safely.  
# - **Resolution**: `resolve_pronoun` and `fill_missing_entities` handle vague or incomplete user input.  
# - **Inspection**: `snapshot` gives a full history for debugging.  

# Together, this module acts as a **short-term conversational memory system**: it logs commands, cleans them, and resolves pronouns or missing entities so the assistant can understand vague follow-ups like “send it again” or “message him.”  

# ---

# 👉 Would you like me to also create a **flow diagram** showing how a user utterance like `"send again"` travels through `update_from_command → fill_missing_entities → resolve_pronoun → get_most_recent` to become a fully resolved command? That would make the pipeline crystal clear.