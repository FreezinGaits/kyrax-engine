# kyrax_core/os_policy.py
"""
OS policy configuration and helpers for KYRAX.
Small, deterministic helpers used by GuardManager and OSSkill.
"""

from typing import Iterable, Optional
import os

ALLOWED_OS_INTENTS = ["open_app", "close_app", "set_volume", "mute", "unmute"]
HIGH_RISK_INTENTS = ["shutdown", "restart", "sleep"]

def _env_bool(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "y")

def dry_run_enabled() -> bool:
    """
    Return True when the system should behave in dry-run / safe mode.
    Controlled by:
      - KYRAX_FORCE_DRY_RUN=1  -> force dry-run (highest priority)
      - KYRAX_OS_DRY_RUN=true  -> normal toggle (default true)
    """
    if _env_bool("KYRAX_FORCE_DRY_RUN", "0"):
        return True
    # default to true for safety if unset
    return _env_bool("KYRAX_OS_DRY_RUN", "true")

def is_high_risk_intent(intent: Optional[str]) -> bool:
    if not intent:
        return False
    return intent.lower() in {i.lower() for i in (HIGH_RISK_INTENTS or [])}

def required_roles_for_intent(intent: Optional[str], override_map: Optional[dict] = None) -> Optional[Iterable[str]]:
    """
    Return roles required for the given intent. If override_map provided, consult it first.
    """
    if not intent:
        return None
    intent_low = intent.lower()
    if override_map and intent in override_map:
        return override_map[intent]
    if is_high_risk_intent(intent_low):
        return ("admin",)
    return None
