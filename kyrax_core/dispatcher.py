# kyrax_core/dispatcher.py
from typing import Optional, Dict, Any
import time
import traceback

from kyrax_core.skill_registry import SkillRegistry
from kyrax_core.command import Command
from kyrax_core.skill_base import SkillResult, SkillExecutionError


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
    """

    def __init__(self, registry: Optional[SkillRegistry] = None, min_confidence: float = 0.0):
        self.registry = registry or SkillRegistry()
        self.min_confidence = float(min_confidence)

    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None, timeout_s: Optional[float] = None) -> SkillResult:
        """
        Execute a Command.

        - context: optional runtime context passed to skill.execute
        - timeout_s: optional timeout in seconds (Phase-1: cooperative only — skill must return)
        """
        if not isinstance(command, Command):
            raise DispatchError("Invalid command object")

        if not command.is_valid():
            raise DispatchError("Command failed basic validation")

        # Confidence gating (optional)
        if command.confidence < self.min_confidence:
            return SkillResult(False, f"Low confidence ({command.confidence:.2f}) — refusing to execute")

        # Find handler
        handler = self.registry.find_handler(command)
        if handler is None:
            return SkillResult(False, f"No skill registered to handle intent '{command.intent}' in domain '{command.domain}'")

        # Execute (Phase-1: blocking, simple timeout via polling)
        start = time.time()
        try:
            # If timeout provided, we still call handler.execute(); skills should be quick in Phase-1.
            result = handler.execute(command, context=context or {})
            if not isinstance(result, SkillResult):
                # Normalize fallback
                return SkillResult(False, f"Skill '{handler.name}' returned invalid result type")
        except Exception as exc:
            # Catch skill exceptions and return structured failure
            tb = traceback.format_exc()
            return SkillResult(False, f"Skill '{handler.name}' raised exception: {exc}", {"traceback": tb})

        # Timeout check (best-effort)
        if timeout_s is not None:
            elapsed = time.time() - start
            if elapsed > timeout_s:
                return SkillResult(False, f"Execution exceeded timeout {timeout_s}s (elapsed {elapsed:.2f}s)")

        return result

    def dispatch(self, command: Command, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Alternative API for chain_executor compatibility.
        Wraps execute() and returns a dict-like result instead of SkillResult.
        
        This allows chain_executor and other components expecting dict results to work
        with the real Dispatcher without modification.
        """
        result = self.execute(command, context=context)
        # Convert SkillResult to dict format expected by chain_executor
        return {
            "success": result.success,
            "message": result.message,
            "code": result.code,
            **(result.data or {})
        }
