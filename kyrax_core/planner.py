# kyrax_core/planner.py
from typing import List, Dict, Any, Optional
import re
from datetime import datetime
from .command import Command

# small mapping of intents -> domains (keep consistent with intent_mapper / command_builder)
INTENT_TO_DOMAIN = {
    "open_app": "os",
    "open_file": "file",
    "set_volume": "os",
    "set_dnd": "os",
    "turn_off_notifications": "os",
    "send_message": "application",
    "turn_on": "iot",
    "turn_off": "iot",
    "unknown_plan": "system",
}


class TaskPlanner:
    """
    Simple Task Planner (Brain) that decomposes high-level goals into
    an ordered list of Command objects.

    - Template-driven for common goals (easy to extend).
    - Rule-based extraction for file names and numbers.
    - Safe fallback produces a single 'unknown_plan' command.
    """

    def __init__(self, templates: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        # each template is a list of step descriptors: {"intent": .., "entities": {...}}
        self.templates = templates or self._default_templates()

    def _default_templates(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            # canonical name -> ordered steps
            "prepare_presentation": [
                {"intent": "open_app", "entities": {"app": "powerpoint"}},
                {"intent": "open_file", "entities": {"path": "<presentation_file>"}},
                {"intent": "turn_off_notifications", "entities": {}},
                {"intent": "set_volume", "entities": {"level": 70}},
                {"intent": "set_dnd", "entities": {"enabled": True}},
            ],
            "default_meeting_setup": [
                {"intent": "open_app", "entities": {"app": "calendar"}},
                {"intent": "open_app", "entities": {"app": "video_conference"}},
                {"intent": "set_dnd", "entities": {"enabled": True}},
                {"intent": "set_volume", "entities": {"level": 50}},
            ],
        }

    # ---------- Public API ----------
    def plan(self, goal: str, context: Optional[Dict[str, Any]] = None) -> List[Command]:
        """
        Plan a list of Command objects from a goal string and optional context.
        `context` is a plain dict (e.g., {"last_file": "talk_v2.pptx", ...}).
        """
        goal = (goal or "").strip().lower()
        context = context or {}

        # 1) Template matching (keyword heuristics)
        if self._matches_presentation(goal):
            steps = self.templates.get("prepare_presentation", [])
        elif self._matches_meeting(goal):
            steps = self.templates.get("default_meeting_setup", [])
        else:
            # try heuristic decomposition
            steps = self._heuristic_decompose(goal)

        # 2) Expand placeholders with context where possible
        steps = [self._expand_placeholders(step, context) for step in steps]

        # 3) Convert to Command objects
        commands: List[Command] = []
        for s in steps:
            intent = s.get("intent", "unknown_plan")
            entities = s.get("entities", {}) or {}
            domain = INTENT_TO_DOMAIN.get(intent, "generic")
            cmd = Command(
                intent=intent,
                domain=domain,
                entities=entities,
                confidence=0.9,            # planner-confidence (tunable)
                source="planner"
            )
            commands.append(cmd)

        # if planner produced nothing, emit a safe fallback command
        if not commands:
            commands.append(Command(
                intent="unknown_plan",
                domain="system",
                entities={"goal": goal},
                confidence=0.5,
                source="planner"
            ))
        return commands

    def execute_plan(self, commands: List[Command], dispatcher) -> List[Any]:
        """
        Execute a plan by sending commands to a dispatcher.
        dispatcher must implement a `dispatch(command: Command)` method that returns a result.
        Returns a list of results (dispatcher outputs) in order.
        """
        results = []
        for cmd in commands:
            # dispatch may raise — caller's responsibility to handle
            res = dispatcher.dispatch(cmd)
            results.append(res)
        return results

    # ---------- helpers ----------
    def _matches_presentation(self, text: str) -> bool:
        # look for 'presentation', 'ppt', 'pptx', 'slides'
        return bool(re.search(r"\b(presentation|pptx?|slides?)\b", text))

    def _matches_meeting(self, text: str) -> bool:
        return bool(re.search(r"\b(meeting|conference|call|webinar)\b", text))

    def _heuristic_decompose(self, text: str) -> List[Dict[str, Any]]:
        """
        Produce simple decomposition for goals not covered by templates.
        - tries to find file names (pptx), apps, numbers (volume).
        - returns a short plan or empty -> fallback.
        """
        steps: List[Dict[str, Any]] = []

        # open file if .ppt/.pptx found
        m = re.search(r"([\w\-. ]+\.pptx?)", text)
        if m:
            path = m.group(1).strip()
            steps.append({"intent": "open_file", "entities": {"path": path}})
            return steps

        # if user says 'prepare laptop' + presentation missing filename, rely on default prepare_presentation
        if "prepare" in text and "presentation" in text:
            steps = self.templates.get("prepare_presentation", [])
            return steps

        # numeric volume mention: "set volume to 70"
        m2 = re.search(r"volume\s*(?:to)?\s*(\d{1,3})", text)
        if m2:
            lvl = int(m2.group(1))
            lvl = max(0, min(100, lvl))
            steps.append({"intent": "set_volume", "entities": {"level": lvl}})
            return steps

        # simple "setup meeting" synonyms fallback
        if "setup meeting" in text or "set up meeting" in text:
            steps = self.templates.get("default_meeting_setup", [])
            return steps

        # no decomposition found
        return []

    def _expand_placeholders(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace placeholders like "<presentation_file>" with context values
        (e.g. context.get("last_presentation") or context.get("last_file")).
        """
        step = {"intent": step.get("intent"), "entities": dict(step.get("entities") or {})}
        for k, v in list(step["entities"].items()):
            if isinstance(v, str) and v.startswith("<") and v.endswith(">"):
                placeholder = v[1:-1]  # drop <>
                # try common context keys
                candidate = context.get(placeholder) or context.get(f"last_{placeholder}") or context.get("last_file")
                if candidate:
                    step["entities"][k] = candidate
                else:
                    # leave placeholder as-is (builder or runtime should handle missing)
                    step["entities"][k] = None
        return step
