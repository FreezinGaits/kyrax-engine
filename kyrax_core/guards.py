# kyrax_core/guards.py
"""
Safety / Validation / Guardrails for KYRAX (Phase-3).
- GuardManager.validate(...) is the main entry point.
- It returns a GuardResult that the dispatcher should respect:
    - blocked: True -> DO NOT EXECUTE
    - require_confirmation: True -> ask user, then proceed only if confirmed
    - allowed: True -> safe to dispatch
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable
import time
import threading
import re
# add near other top-level configuration in kyrax_core/guards.py
from kyrax_core.os_policy import (
    ALLOWED_OS_INTENTS,
    HIGH_RISK_INTENTS,
    required_roles_for_intent,
    is_high_risk_intent,
    dry_run_enabled,
)
from kyrax_core.policy_store import get_policy_store
from kyrax_core import config
from kyrax_core.audit import record as audit_record
from kyrax_core.ratelimiter_redis import get_rate_limiter


# simple default config — tune these for your deployment
DEFAULT_RATE_LIMIT = {
    "window_sec": 60,
    "max_requests": 20
}

# intents considered destructive or sensitive by default
DESTRUCTIVE_INTENT_PATTERNS = [
    r"delete", r"remove", r"wipe", r"format", r"factory_reset", r"uninstall",
    r"shutdown", r"reboot", r"erase"
]

SENSITIVE_INTENTS = [
    "send_message",     # sensitive if contacting external recipients
    "send_email",
    "transfer_money",
    "open_port",
    "exfiltrate_data",
]

# required role per intent (simple ACL example)
INTENT_ROLE_REQUIREMENTS = {
    "factory_reset": ["admin"],
    "format_disk": ["admin"],
    "delete_file": ["user", "admin"],  # still may require confirmation
    "unlock_door": ["home_owner", "admin"]
}

# A small whitelist of safe file paths prefixes; anything outside requires confirmation
SAFE_PATH_PREFIXES = ["/home/", "/mnt/storage/"]


@dataclass
class GuardResult:
    allowed: bool
    blocked: bool
    require_confirmation: bool
    reason: Optional[str] = None
    actions: Optional[List[str]] = None  # e.g., ["ask_confirmation", "rate_limited"]


class RateLimiter:
    """In-memory per-user sliding window rate limiter (simple)."""
    def __init__(self, window_sec: int = 60, max_requests: int = 20):
        self.window = window_sec
        self.max = max_requests
        self._store: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> tuple[bool, Optional[str]]:
        now = time.time()
        with self._lock:
            lst = self._store.setdefault(user_id, [])
            # drop older timestamps
            cutoff = now - self.window
            while lst and lst[0] < cutoff:
                lst.pop(0)
            if len(lst) >= self.max:
                return False, f"rate_limit_exceeded: {len(lst)}/{self.max} in {self.window}s"
            lst.append(now)
            return True, None


class GuardManager:
    def __init__(self,
                 rate_limiter: Optional[RateLimiter] = None,
                 role_check_fn: Optional[Callable[[str, List[str]], bool]] = None,
                 skill_registry_checker: Optional[Callable[[Dict[str,Any]], bool]] = None):
        self.rate_limiter = rate_limiter or get_rate_limiter(DEFAULT_RATE_LIMIT["window_sec"], DEFAULT_RATE_LIMIT["max_requests"])
        # role_check_fn(user_roles, required_roles) -> bool
        self.role_check_fn = role_check_fn or (lambda user_roles, required: bool(set(user_roles) & set(required)))
        # skill_registry_checker(command) -> bool (True if a skill exists & allowed)
        self.skill_registry_checker = skill_registry_checker or (lambda cmd: True)

    # ---------- checks ----------
    def _is_destructive(self, cmd) -> bool:
        name = (cmd.intent or "").lower()
        for p in DESTRUCTIVE_INTENT_PATTERNS:
            if re.search(p, name):
                return True
        # also check entities for dangerous path tokens
        if cmd.domain == "file":
            path = str(cmd.entities.get("path") or cmd.entities.get("target") or "")
            if path:
                if path in ("/", "C:\\") or path.lower().startswith("c:\\windows"):
                    return True
                if re.search(r"\b(all|everything|recursive|--all)\b", path.lower()):
                    return True
        return False

    def _sensitive_external_action(self, cmd) -> bool:
        # as before
        if cmd.intent in ("send_email", "send_message"):
            contact = cmd.entities.get("contact") or cmd.entities.get("to")
            if contact and isinstance(contact, str):
                if "@" in contact or re.search(r"https?://", contact):
                    return True
        if cmd.intent in ("transfer_money", "open_port", "exfiltrate_data"):
            return True
        return False

    def _path_requires_confirmation(self, path: str) -> bool:
        if not path:
            return False
        for p in SAFE_PATH_PREFIXES:
            if path.startswith(p):
                return False
        return True

    # ---------- public API ----------
    def validate(self, cmd, user: Dict[str,Any], context: Optional[Dict[str,Any]] = None) -> GuardResult:
        """
        Validate a built Command. `user` is a dict with keys: id, roles (list), name, etc.
        Returns GuardResult. The dispatcher must obey it.
        """
        context = context or {}
        user_id = str(user.get("id", "anonymous"))
        user_roles = user.get("roles", []) or []

        # 1) rate limit
        ok, msg = self.rate_limiter.check(user_id)
        if not ok:
            audit_record(
                "guard_rate_limited",
                {"user_id": user_id, "reason": msg}
            )
            return GuardResult(
                allowed=False,
                blocked=True,
                require_confirmation=False,
                reason=msg,
                actions=["rate_limited"],
            )


        # 2) skill capability check
        try:
            skill_ok = self.skill_registry_checker(cmd)
        except Exception:
            skill_ok = False
        if not skill_ok:
            return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="no_skill_available", actions=["blocked_no_skill"])

        # -------------------------
        # OS-specific policy checks
        # -------------------------
        try:
            # Import lazily so module remains import-safe if os_policy missing
            from kyrax_core.os_policy import ALLOWED_OS_INTENTS, HIGH_RISK_INTENTS, dry_run_enabled
        except Exception:
            ALLOWED_OS_INTENTS = None
            HIGH_RISK_INTENTS = None
            dry_run_enabled = lambda: False  # default: not dry-run

        # If this is an OS-domain command, apply stricter policy
        if getattr(cmd, "domain", "") == "os":
            intent = (cmd.intent or "").lower()

            # If an allow-list exists, reject unknown OS intents
            if ALLOWED_OS_INTENTS is not None:
                allowed_lower = {i.lower() for i in (ALLOWED_OS_INTENTS or [])}
                highrisk_lower = {i.lower() for i in (HIGH_RISK_INTENTS or [])}
                if intent not in allowed_lower and intent not in highrisk_lower:
                    return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="os_intent_not_allowed", actions=["blocked_os_intent"])

            # If dry-run mode enabled, block high-risk intents outright
            # 🔒 DRY-RUN POLICY (STRICT):
            # In dry-run mode, ALL high-risk OS intents are BLOCKED at validation time,
            # even for admin. Runtime override is NOT allowed here.
            if (
                dry_run_enabled()
                and HIGH_RISK_INTENTS is not None
                and intent in {i.lower() for i in HIGH_RISK_INTENTS}
            ):
                audit_record(
                    "guard_blocked_dry_run",
                    {"user_id": user_id, "intent": intent}
                )
                return GuardResult(
                    allowed=False,
                    blocked=True,
                    require_confirmation=False,
                    reason="dry_run_blocked",
                    actions=["blocked_dry_run"],
                )





            # If this is a high-risk OS intent, require explicit confirmation and admin role
            if HIGH_RISK_INTENTS is not None and intent in {i.lower() for i in HIGH_RISK_INTENTS}:
                # require admin role for destructive OS actions
                if "admin" not in user_roles:
                    audit_record(
                        "guard_blocked_destructive_no_admin",
                        {"user_id": user_id, "intent": intent}
                    )
                    return GuardResult(
                        allowed=False,
                        blocked=True,
                        require_confirmation=False,
                        reason="destructive_action_requires_admin",
                        actions=["blocked_destructive"]
                    )

                # If admin, require confirmation
                audit_record(
                    "guard_require_confirmation",
                    {"user_id": user_id, "intent": intent}
                )
                return GuardResult(
                    allowed=False,
                    blocked=False,
                    require_confirmation=True,
                    reason="os_high_risk",
                    actions=["confirm_destructive"]
                )


        # 3) role-based ACL
        required_roles = INTENT_ROLE_REQUIREMENTS.get(cmd.intent)
        if required_roles:
            if not self.role_check_fn(user_roles, required_roles):
                return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="insufficient_permissions", actions=["blocked_permissions"])

        # 4) destructive check (generic)
        if self._is_destructive(cmd):
            if "admin" not in user_roles:
                return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="destructive_action_requires_admin", actions=["blocked_destructive"])
            return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="destructive_action_confirm", actions=["confirm_destructive"])

        # 5) sensitive external actions
        if self._sensitive_external_action(cmd):
            return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="sensitive_external", actions=["confirm_sensitive"])

        # 6) path checks for file domain
        if cmd.domain == "file":
            path = cmd.entities.get("path") or cmd.entities.get("target") or ""
            if isinstance(path, str) and self._path_requires_confirmation(path):
                return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="path_outside_safe_prefix", actions=["confirm_path"])

        # otherwise allowed
        return GuardResult(allowed=True, blocked=False, require_confirmation=False, reason="ok", actions=[])

    def guard_and_dispatch(
        self,
        cmd,
        user: Dict[str, Any],
        dispatcher_callable,
        context: Optional[Dict[str, Any]] = None,
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Runtime helper: validate → confirm → dispatch.
        Returns a UI-friendly dict.
        """

        res = self.validate(cmd, user, context)

        if res.blocked:
            return {
                "status": "blocked",
                "reason": res.reason,
                "actions": res.actions,
            }

        if res.require_confirmation:
            if not confirm_fn:
                return {
                    "status": "blocked",
                    "reason": "confirmation_required_but_no_confirm_fn",
                }

            ok = False
            try:
                ok = confirm_fn(res.reason or "Confirm execution?")
            except Exception:
                ok = False

            if not ok:
                return {
                    "status": "cancelled",
                    "reason": "user_declined_confirmation",
                }

        # Safe to execute
        try:
            result = dispatcher_callable(cmd)
            audit_record(
                "dispatch_executed",
                {
                    "user_id": str(user.get("id", "anonymous")),
                    "intent": cmd.intent,
                    "domain": cmd.domain,
                }
            )
            return {
                "status": "executed",
                "result": result,
            }

        except Exception as e:
            audit_record(
                "dispatch_error",
                {
                    "user_id": str(user.get("id", "anonymous")),
                    "intent": getattr(cmd, "intent", None),
                    "error": str(e),
                }
            )
            return {
                "status": "error",
                "reason": str(e),
            }

