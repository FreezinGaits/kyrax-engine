# kyrax_core/skill_registry.py
from typing import List, Optional
from kyrax_core.skill_base import Skill
from kyrax_core.command import Command


class SkillRegistry:
    """
    Simple registry to hold available skills and find the one that can handle a Command.
    """

    def __init__(self):
        self._skills: List[Skill] = []

    def register(self, skill: Skill) -> None:
        if any(s.name == skill.name for s in self._skills):
            raise ValueError(f"Skill with name '{skill.name}' already registered")
        self._skills.append(skill)

    def unregister(self, skill_name: str) -> None:
        self._skills = [s for s in self._skills if s.name != skill_name]

    def find_handler(self, command: Command) -> Optional[Skill]:
        """
        Returns the first skill that claims it can handle the command.
        Registry order determines priority. You can extend to scoring later.
        """
        for skill in self._skills:
            try:
                if skill.can_handle(command):
                    return skill
            except Exception:
                # skill should never crash during can_handle; skip if it does
                continue
        return None

    def list_skills(self) -> List[str]:
        return [s.name for s in self._skills]