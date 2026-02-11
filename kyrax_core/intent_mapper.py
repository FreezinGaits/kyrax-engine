# kyrax_core/intent_mapper.py
from typing import Dict, Any, Optional
from .command import Command


def map_nlu_to_command(
    nlu_payload: Dict[str, Any],
    default_domain: Optional[str] = None,
    source: str = "text"
) -> Command:
    intent = (nlu_payload.get("intent") or nlu_payload.get("name") or "").lower()
    slots = nlu_payload.get("slots", {}) or nlu_payload.get("entities", {}) or {}
    confidence = float(nlu_payload.get("confidence", 1.0))
    meta = nlu_payload.get("meta", {})

    # ---------- CANONICAL OS INTENT MAPPING ----------
    OS_INTENT_MAP = {
        "set_volume": "set_volume",
        "change_volume": "set_volume",
        "adjust_volume": "set_volume",
        "volume": "set_volume",
        "mute": "mute",
        "mute_volume": "mute",
        "unmute": "unmute",
        "unmute_volume": "unmute",
        "open_app": "open_app",
        "launch_app": "open_app",
        "open": "open_app",
        "close_app": "close_app",
        "close": "close_app",
    }

    if intent in OS_INTENT_MAP:
        canon_intent = OS_INTENT_MAP[intent]
        domain = "os"
    else:
        canon_intent = intent
        domain = default_domain or guess_domain_from_intent(intent, slots)

    entities = normalize_entities(slots)

    return Command(
        intent=canon_intent,
        domain=domain,
        entities=entities,
        confidence=confidence,
        source=source,
        meta=meta,
    )



def guess_domain_from_intent(intent: str, slots: Dict[str, Any]) -> str:
    """Simple heuristics to infer domain from intent name or slots."""
    intent_lower = intent.lower()
    if any(k in intent_lower for k in ("send", "message", "sms", "whatsapp", "mail")):
        return "application"
    # Built-in Python function.
    # Returns True if at least one element in the iterable is True.
    # Returns False only if all are False.

    if any(k in intent_lower for k in ("open", "launch", "start", "close", "terminate")):
        return "os"
    if any(k in intent_lower for k in ("turn", "switch", "light", "fan", "ac", "thermostat")):
        return "iot"
    if "url" in slots or "search" in intent_lower:
        return "web"
    return "system"


def normalize_entities(slots: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert NLU slot names to standard KYRAX entity keys.
    Extend this mapping with project-specific synonyms.
    """
    mapping = {
        "contact": "contact",
        "name": "contact",
        "person": "contact",
        "message": "text",
        "text": "text",
        "body": "text",
        "app": "app",
        "application": "app",
        "file": "path",
        "path": "path",
        "device": "device",
        "location": "location",
        "media": "media",
        "index": "index",
        "n": "index",
        "count": "count"
    }

    normalized = {}
    for k, v in slots.items():
        key = mapping.get(k.lower(), k.lower())
        normalized[key] = v
    return normalized
