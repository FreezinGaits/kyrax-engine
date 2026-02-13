# kyrax_core/contact_resolver.py
"""
ContactResolver — Phase 4 (Command Building)

Responsibilities:
- Load and manage contact registry data
- Normalize and resolve contact names
- Perform fuzzy matching and ambiguity detection
- Provide ranked candidates for clarification

Non-responsibilities:
- No UI / Playwright logic
- No message sending
- No persistence side-effects beyond loading contacts

Used exclusively by CommandBuilder before execution.
"""


from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any
import json
import os
import difflib
import re
from difflib import SequenceMatcher


def _norm(s: str) -> str:
    # Remove punctuation and extra whitespace, convert to lower
    s = re.sub(r'[^\w\s]', '', s or "")
    return re.sub(r'\s+', ' ', s).strip().lower()

# Common voice transcription errors map (canonical correction)
TRANSCRIPTION_CORRECTIONS = {
    "gotham": "gautam sharma",
    "gothan": "gautam sharma",
    "gautam": "gautam sharma",
}


class ContactResolver:
    """
    ContactResolver loads a contacts JSON mapping (canonical_name -> metadata).
    Recommended contacts.json layout:
      {
        "Akshat Pawar": {"name": "Akshat Pawar", "whatsapp_name": "Akshat Pawar", "phone": "+91..."},
        ...
      }

    Public methods:
     - find_best(query) -> canonical_name | None
     - candidates(query, n=5, cutoff=0.4) -> List[(canonical_name, score)]
    """

    def __init__(self, contacts_path: Optional[str] = None, contacts_dict: Optional[Dict[str, Any]] = None):
        self.contacts_path = contacts_path
        self._contacts = {}
        if contacts_dict is not None:
            self._contacts = dict(contacts_dict)
        elif contacts_path:
            try:
                with open(os.path.abspath(contacts_path), "r", encoding="utf-8") as f:
                    self._contacts = json.load(f)
                # >>> os.path.abspath("data/contacts.json")
                # 'D:\\Code Playground\\kyrax-engine\\data\\contacts.json'
            except Exception:
                self._contacts = {}

        # build search indexes
        self._keys = list(self._contacts.keys())
        # precompute searchable name variants (lowercased)
        self._variants = {}
        for k, v in self._contacts.items():
            names = set()
            names.add(_norm(k))
            if isinstance(v, dict):
                for field in ("whatsapp_name", "name", "alias"):
                    val = v.get(field)
                    if val:
                        names.add(_norm(val))
                phone = v.get("phone")
                if phone:
                    names.add(re.sub(r'\D', '', str(phone)))
            self._variants[k] = list(names)
# (Note: duplicates collapse because names is a set before converting to list.)
    def reload(self, contacts_path: Optional[str] = None):
        """Reload from disk (useful during development)."""
        if contacts_path:
            self.contacts_path = contacts_path
        if self.contacts_path:
            with open(os.path.abspath(self.contacts_path), "r", encoding="utf-8") as f:
                self._contacts = json.load(f)
        else:
            self._contacts = {}
        self._keys = list(self._contacts.keys())
        self._variants = {}
        for k, v in self._contacts.items():
            names = set()
            names.add(_norm(k))
            if isinstance(v, dict):
                for field in ("whatsapp_name", "name", "alias"):
                    val = v.get(field)
                    if val:
                        names.add(_norm(val))
                phone = v.get("phone")
                if phone:
                    names.add(re.sub(r'\D', '', str(phone)))
            self._variants[k] = list(names)


    # _score_pair uses SequenceMatcher to compute a similarity score between the normalized query and candidate. It’s a way to do fuzzy contact search so that near matches (typos, small differences) can still be recognized.
    def _score_pair(self, query_norm: str, candidate_norm: str) -> float:
        # sequence matcher ratio is a decent baseline
        return float(SequenceMatcher(None, query_norm, candidate_norm).ratio())
        # The first parameter is called isjunk.
        # It’s a function you can provide to tell the matcher which characters (or elements) should be ignored when comparing.
        # Example: you might want to ignore spaces or punctuation when comparing strings.
        # resolver.candidates(t, n=1, cutoff=0.4)


    # First checks phone digits.
    # Then checks exact name match.
    # Then falls back to substring or fuzzy similarity.
    # Returns the top n candidates with scores ≥ cutoff.
    def candidates(self, query: str, n: int = 5, cutoff: float = 0.40) -> List[Tuple[str, float]]:
        """
        Return up to n candidate canonical names with score >= cutoff (descending by score).
        """
        q = _norm(query)
        if not q:
            return []

        scored: List[Tuple[str, float]] = []

        # check corrections map
        if q in TRANSCRIPTION_CORRECTIONS:
            corrected_key = TRANSCRIPTION_CORRECTIONS[q]
            # Verify the corrected key exists in contacts
            # We need to find the exact key that matches the normalized correction
            # This is a bit indirect, but effective.
            # actually, if corrections maps 'gotham' -> 'gautam sharma', we should return 'Gautam Sharma' (the real key)
            for k in self._keys:
                if _norm(k) == _norm(corrected_key):
                    return [(k, 1.0)]

        # phone exact match check
        digits = re.sub(r'\D', '', query)
        if digits:
            for k, v in self._contacts.items():
                ph = (v.get("phone") or "") if isinstance(v, dict) else ""
                if digits == re.sub(r'\D', '', str(ph)):
                    return [(k, 1.0)]

        # exact key match (case-insensitive)
        for k in self._keys:
            if q == _norm(k):
                return [(k, 1.0)]

        # scan variants for substring or fuzzy
        for k, variants in self._variants.items():
            best = 0.0
            for cand in variants:
                if q in cand or cand in q:
                    best = max(best, 0.8)
                else:
                    best = max(best, self._score_pair(q, cand)) # q is the token provided by the query and cand is the candidate from the contact list
            if best >= cutoff:
                scored.append((k, best))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]



    # Accepts if only one candidate.
    # Accepts if top candidate is clearly stronger than second.
    # Accepts if top candidate is very strong.
    # Otherwise, returns None to avoid mistakes as if the difference is too less then it means that the query is ambiguous and we should ask for clarification instead of guessing wrong.
    def find_best(self, query: str, cutoff: float = 0.6) -> Optional[str]:
        """
        Return a single canonical name if a candidate surpasses cutoff; otherwise None.
        """
        cand = self.candidates(query, n=5, cutoff=cutoff)
        if not cand:
            return None
        # If top candidate is sufficiently better than second, accept it
        if len(cand) == 1:
            return cand[0][0]
        top_name, top_score = cand[0]
        _, second_score = cand[1]
        # acceptance heuristic
        if top_score >= cutoff and (top_score - second_score >= 0.10 or top_score >= 0.85):
            return top_name
        # if top score very high, accept
        if top_score >= 0.90:
            return top_name
        return None

    def get_raw_contacts(self) -> Dict[str, Any]:
        return self._contacts.copy()
