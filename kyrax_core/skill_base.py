# kyrax_core/skill_base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from kyrax_core.command import Command


@dataclass
class SkillResult:
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    code: Optional[int] = None


class SkillExecutionError(Exception):
    """Raised when a skill fails during execution."""
    pass


class Skill(ABC):
    """
    Skill contract (must be implemented by all skills).
    Skills are pure executors — they do not make planning/intent decisions.
    """

    name: str = "base"

    @abstractmethod
    def can_handle(self, command: Command) -> bool:
        """
        Return True if this skill can execute the supplied Command.
        Keep checks lightweight (intent/domain/entities).
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        """
        Perform the task described by `command`.
        Should return SkillResult (success/failure). Must NOT call other skills.
        """
        raise NotImplementedError
