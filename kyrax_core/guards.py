# kyrax_core/guards.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable, Iterable
import time
import threading
import re

import kyrax_core.os_policy as os_policy


DEFAULT_RATE_LIMIT = {"window_sec": 60, "max_requests": 20}

DESTRUCTIVE_INTENT_PATTERNS = [
    r"delete", r"remove", r"wipe", r"format", r"factory_reset", r"uninstall",
    r"shutdown", r"reboot", r"erase"
]

SAFE_PATH_PREFIXES = ["/home/", "/mnt/storage/"]

@dataclass
class GuardResult:
    allowed: bool
    blocked: bool
    require_confirmation: bool
    reason: Optional[str] = None
    actions: Optional[List[str]] = None

class RateLimiter:
    def __init__(self, window_sec: int = 60, max_requests: int = 20):
        self.window = window_sec
        self.max = max_requests
        self._store: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> tuple[bool, Optional[str]]:
        now = time.time()
        with self._lock:
            lst = self._store.setdefault(user_id, [])
            cutoff = now - self.window
            while lst and lst[0] < cutoff:
                lst.pop(0)
            if len(lst) >= self.max:
                return False, f"rate_limit_exceeded: {len(lst)}/{self.max} in {self.window}s"
            lst.append(now)
            return True, None

class GuardManager:
    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        role_check_fn: Optional[Callable[[Iterable[str], Iterable[str]], bool]] = None,
        skill_registry_checker: Optional[Callable[[Dict[str, Any]], bool]] = None,
        intent_roles_map: Optional[Dict[str, Iterable[str]]] = None
    ):
        """
        intent_roles_map: mapping intent -> iterable roles (e.g. {"shutdown": ("admin",)})
        """
        self.rate_limiter = rate_limiter or RateLimiter(DEFAULT_RATE_LIMIT["window_sec"], DEFAULT_RATE_LIMIT["max_requests"])
        self.role_check_fn = role_check_fn or (lambda user_roles, required: bool(set(user_roles) & set(required)))
        self.skill_registry_checker = skill_registry_checker or (lambda cmd: True)
        self.intent_roles_map = intent_roles_map or {}

    def _is_destructive(self, cmd) -> bool:
        name = (cmd.intent or "").lower()
        for p in DESTRUCTIVE_INTENT_PATTERNS:
            if re.search(p, name):
                return True
        if cmd.domain == "file":
            path = str(cmd.entities.get("path") or cmd.entities.get("target") or "")
            if path:
                if path in ("/", "C:\\") or path.lower().startswith("c:\\windows"):
                    return True
                if re.search(r"\b(all|everything|recursive|--all)\b", path.lower()):
                    return True
        return False

    def _sensitive_external_action(self, cmd) -> bool:
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

    def validate(self, cmd, user: Dict[str,Any], context: Optional[Dict[str,Any]] = None) -> GuardResult:
        context = context or {}
        user_id = str(user.get("id", "anonymous"))
        user_roles = user.get("roles", []) or []

        ok, msg = self.rate_limiter.check(user_id)
        if not ok:
            return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason=msg, actions=["rate_limited"])

        try:
            skill_ok = self.skill_registry_checker(cmd)
        except Exception:
            skill_ok = False
        if not skill_ok:
            return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="no_skill_available", actions=["blocked_no_skill"])

        if getattr(cmd, "domain", "") == "os":
            intent = (cmd.intent or "").lower()
            allowed_lower = {i.lower() for i in (os_policy.ALLOWED_OS_INTENTS or [])}
            highrisk_lower = {i.lower() for i in (os_policy.HIGH_RISK_INTENTS or [])}

            # Reject unknown OS intents
            if os_policy.ALLOWED_OS_INTENTS is not None:
                if intent not in allowed_lower and intent not in highrisk_lower:
                    return GuardResult(
                        allowed=False,
                        blocked=True,
                        require_confirmation=False,
                        reason="os_intent_not_allowed",
                        actions=["blocked_os_intent"],
                    )

            # -------------------------------
            # DRY-RUN MODE (hard safety)
            # -------------------------------
            # DRY-RUN MODE (simulation safety)
            if os_policy.dry_run_enabled() and intent in highrisk_lower:
                # non-admins still blocked
                if "admin" not in user_roles:
                    return GuardResult(
                        allowed=False,
                        blocked=True,
                        require_confirmation=False,
                        reason="dry_run_blocked_non_admin",
                        actions=["blocked_dry_run"],
                    )

                # admins → confirmation required, execution will be simulated by OSSkill
                return GuardResult(
                    allowed=False,
                    blocked=False,
                    require_confirmation=True,
                    reason="dry_run_high_risk_confirm",
                    actions=["confirm_destructive"],
                )


            # -------------------------------
            # NORMAL MODE (role + confirm)
            # -------------------------------
            if intent in highrisk_lower:
                # must be admin
                if "admin" not in user_roles:
                    return GuardResult(
                        allowed=False,
                        blocked=True,
                        require_confirmation=False,
                        reason="destructive_action_requires_admin",
                        actions=["blocked_destructive"],
                    )

                # admin → confirmation required
                return GuardResult(
                    allowed=False,
                    blocked=False,
                    require_confirmation=True,
                    reason="os_high_risk",
                    actions=["confirm_destructive"],
                )


        # role-based mapping for other intents
        required_roles = self.intent_roles_map.get(cmd.intent)
        if required_roles:
            if not self.role_check_fn(user_roles, required_roles):
                return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="insufficient_permissions", actions=["blocked_permissions"])

        if self._is_destructive(cmd):
            if "admin" not in user_roles:
                return GuardResult(allowed=False, blocked=True, require_confirmation=False, reason="destructive_action_requires_admin", actions=["blocked_destructive"])
            return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="destructive_action_confirm", actions=["confirm_destructive"])

        if self._sensitive_external_action(cmd):
            return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="sensitive_external", actions=["confirm_sensitive"])

        if cmd.domain == "file":
            path = cmd.entities.get("path") or cmd.entities.get("target") or ""
            if isinstance(path, str) and self._path_requires_confirmation(path):
                return GuardResult(allowed=False, blocked=False, require_confirmation=True, reason="path_outside_safe_prefix", actions=["confirm_path"])

        return GuardResult(allowed=True, blocked=False, require_confirmation=False, reason="ok", actions=[])

    def guard_and_dispatch(self, cmd, user: Dict[str, Any], dispatcher_callable, context: Optional[Dict[str, Any]] = None, confirm_fn: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
        res = self.validate(cmd, user, context)
        if res.blocked:
            return {"status":"blocked","reason":res.reason,"actions":res.actions}
        if res.require_confirmation:
            if not confirm_fn:
                return {"status":"blocked","reason":"confirmation_required_but_no_confirm_fn"}
            ok = False
            try:
                ok = confirm_fn(res.reason or "Confirm execution?")
            except Exception:
                ok = False
            if not ok:
                return {"status":"cancelled","reason":"user_declined_confirmation"}
        try:
            result = dispatcher_callable(cmd)
            return {"status":"executed","result":result}
        except Exception as e:
            return {"status":"error","reason":str(e)}
