# File: kyrax_core/dispatcher.py
from typing import Optional, Dict, Any, Callable
import time
import traceback

from kyrax_core.skill_registry import SkillRegistry
from kyrax_core.command import Command
from kyrax_core.skill_base import SkillResult, SkillExecutionError
from kyrax_core.guards import GuardManager, GuardResult  # guard types for typing clarity


class DispatchError(Exception):
    """Raised for dispatcher-level failures (no handler / runtime error)."""
    pass


class Dispatcher:
    """
    Executor Dispatcher — Phase 1.

    Responsibilities:
    - Accept Command objects
    - Ask SkillRegistry for a handler
    - Execute handler.execute(command, context)
    - Return SkillResult (or a normalized failure result)

    New in Phase 2: optional GuardManager integration. Pass a GuardManager instance
    to the constructor and optionally default_user and default_confirm_fn to use
    when caller does not provide them on execute().
    """

    def __init__(self, registry: Optional[SkillRegistry] = None, min_confidence: float = 0.0,
                 guard_manager: Optional[GuardManager] = None,
                 default_user: Optional[Dict[str, Any]] = None,
                 default_confirm_fn: Optional[Callable[[str], bool]] = None):
        self.registry = registry or SkillRegistry()
        self.min_confidence = float(min_confidence)
        self.guard_manager = guard_manager
        # default user used if caller didn't supply a user to execute()
        self.default_user = default_user or {"id": "local", "roles": []}
        # default confirm function used for interactive confirmations when not supplied by caller
        # signature: confirm_fn(prompt: str) -> bool
        self.default_confirm_fn = default_confirm_fn

    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None,
                timeout_s: Optional[float] = None, user: Optional[Dict[str, Any]] = None,
                confirm_fn: Optional[Callable[[str], bool]] = None) -> SkillResult:
        """
        Execute a Command.

        - context: optional runtime context passed to skill.execute
        - timeout_s: optional timeout in seconds (Phase-1: cooperative only — skill must return)
        - user: optional actor dict {id, roles, name} used for Guard checks
        - confirm_fn: optional confirmation callable for Guard-required confirmations
        """
        if not isinstance(command, Command):
            raise DispatchError("Invalid command object")

        if not command.is_valid():
            raise DispatchError("Command failed basic validation")

        # Confidence gating (optional)
        if command.confidence < self.min_confidence:
            return SkillResult(False, f"Low confidence ({command.confidence:.2f}) — refusing to execute")

        # ---------- guard checks (Phase 2) ----------
        if self.guard_manager:
            u = user or self.default_user or {"id": "anonymous", "roles": []}
            try:
                res = self.guard_manager.validate(command, u, context=context)
            except Exception as e:
                # If guard fails badly, fail-safe: block
                return SkillResult(False, f"Guard validation error: {e}")

            if res.blocked:
                return SkillResult(False, f"Blocked by guard: {res.reason}", {"actions": res.actions})

            if res.require_confirmation:
                # Prefer function provided at call time, else default_confirm_fn, else reject
                fn = confirm_fn or self.default_confirm_fn
                if not fn:
                    return SkillResult(False, f"Confirmation required: {res.reason}", {"actions": res.actions})
                prompt = f"Confirm action: {res.reason}. Command: {command}. Proceed?"
                try:
                    ok = fn(prompt)
                except Exception as e:
                    return SkillResult(False, f"Confirmation function failed: {e}")
                if not ok:
                    return SkillResult(False, "User declined confirmation", {"actions": ["user_declined"]})
                # if confirmed, continue to dispatch normally

        # Find handler
        handler = self.registry.find_handler(command)
        if handler is None:
            return SkillResult(False, f"No skill registered to handle intent '{command.intent}' in domain '{command.domain}'")

        # Execute (Phase-1: blocking, simple timeout via polling)
        start = time.time()
        try:
            result = handler.execute(command, context=context or {})
            if not isinstance(result, SkillResult):
                # Normalize fallback
                return SkillResult(False, f"Skill '{handler.name}' returned invalid result type")
        except Exception as exc:
            tb = traceback.format_exc()
            return SkillResult(False, f"Skill '{handler.name}' raised exception: {exc}", {"traceback": tb})

        # Timeout check (best-effort)
        if timeout_s is not None:
            elapsed = time.time() - start
            if elapsed > timeout_s:
                return SkillResult(False, f"Execution exceeded timeout {timeout_s}s (elapsed {elapsed:.2f}s)")

        return result

    def dispatch(self, command: Command, context: Optional[Dict[str, Any]] = None,
                 user: Optional[Dict[str, Any]] = None, confirm_fn: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
        """
        Alternative API for chain_executor compatibility.
        Wraps execute() and returns a dict-like result instead of SkillResult.
        Keeps optional guard args for compatibility with Phase 2.
        """
        result = self.execute(command, context=context, user=user, confirm_fn=confirm_fn)
        return {
            "success": result.success,
            "message": result.message,
            "code": result.code,
            **(result.data or {})
        }
