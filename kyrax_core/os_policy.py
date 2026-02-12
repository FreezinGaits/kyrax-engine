# kyrax_core/os_policy.py
"""
OS automation policy + helpers (Phase-0).
Single place to configure which OS intents are allowed, which are high-risk,
and what roles/confirmation they require.

Design goals:
 - Data-driven: change lists here, no code edits required later.
 - Safe defaults: dry-run default, high-risk intents require admin+confirmation.
 - Small helpers for guards and pipeline to call.
"""

from typing import List, Dict, Optional
from kyrax_core import config
import os

# --- Default allowed OS intents (conservative) ---
# Modify this list to expand/shrink allowed surface.
ALLOWED_OS_INTENTS: List[str] = [
    "open_app",
    "close_app",
    "set_volume",
    "mute",
    "unmute",
    "browser_search"
    # optional next-phase features (keep commented until implemented):
    # "set_brightness",
    # "reveal_file",
]

# --- High-risk OS intents (require stronger checks) ---
HIGH_RISK_INTENTS: List[str] = [
    "shutdown",
    "restart",
    "sleep",
    # Add any other destructive ops here (e.g., "factory_reset") but only if implemented.
]

# --- Role requirements per intent (can be extended) ---
# Keys are intent names; values are lists of roles required to execute (empty means no role required).
INTENT_ROLE_REQUIREMENTS: Dict[str, List[str]] = {
    # default: no special role needed for low-risk ops
    "open_app": [],
    "close_app": [],
    "set_volume": [],
    "mute": [],
    "unmute": [],
    # high-risk intents require admin by default
    "shutdown": ["admin"],
    "restart": ["admin"],
    "sleep": ["admin"],
}

# --- Runtime toggles via environment variables ---
# Toggle dry-run: when "true" (default) OSSkill must not perform destructive actions for real.
KYRAX_OS_DRY_RUN: bool = os.environ.get("KYRAX_OS_DRY_RUN", "true").lower() in ("1", "true", "yes")

# Allow overriding the allowed intents list from an environment variable (comma separated)
_env_allowed = os.environ.get("KYRAX_OS_ALLOWED", "")
if _env_allowed:
    try:
        ALLOWED_OS_INTENTS = [s.strip() for s in _env_allowed.split(",") if s.strip()]
    except Exception:
        # ignore parsing errors and keep defaults
        pass

# Helpers -------------------------------------------------
def is_intent_allowed(intent: Optional[str]) -> bool:
    if not intent:
        return False
    return intent in ALLOWED_OS_INTENTS or intent in HIGH_RISK_INTENTS

def is_high_risk_intent(intent: Optional[str]) -> bool:
    if not intent:
        return False
    return intent in HIGH_RISK_INTENTS

def required_roles_for_intent(intent: Optional[str]) -> List[str]:
    if not intent:
        return []
    return INTENT_ROLE_REQUIREMENTS.get(intent, [])

# def dry_run_enabled() -> bool:
#     """
#     Dry-run is ON by default.
#     Real destructive actions require explicit opt-in.
#     """
#     if os.environ.get("KYRAX_FORCE_DRY_RUN") == "1":
#         return True
#     return os.environ.get("KYRAX_ALLOW_REAL_POWER_ACTIONS") != "1"

def dry_run_enabled() -> bool:
    """
    Return True when the system must NOT perform destructive or real system actions.
    Priority:
      - KYRAX_FORCE_DRY_RUN (True) => dry-run ON
      - else: dry-run = not KYRAX_ALLOW_REAL_POWER_ACTIONS (safe default)
    """
    if getattr(config, "KYRAX_FORCE_DRY_RUN", False):
        return True
    # invert allow flag: if allow_real is False -> dry-run enabled
    return not getattr(config, "KYRAX_ALLOW_REAL_POWER_ACTIONS", False)