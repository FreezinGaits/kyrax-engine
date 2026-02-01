# skills/os_skill.py
import platform
import shutil
import subprocess
from typing import Optional
from kyrax_core.skill_base import Skill, SkillResult
from kyrax_core.command import Command


class OSSkill(Skill):
    name = "os_control"

    def __init__(self, dry_run: bool = True):
        """
        dry_run: when True, do not actually launch system processes (safe for testing).
        Set to False when you are sure and want to allow system-level actions.
        """
        self.dry_run = dry_run

    def can_handle(self, command: Command) -> bool:
        return command.domain == "os" and command.intent.lower() in ("open_app", "launch", "close_app")

    def _open_platform(self, executable: str) -> Optional[subprocess.Popen]:
        system = platform.system().lower()
        # Prefer os.startfile on Windows via subprocess-like call
        try:
            if system == "windows":
                if self.dry_run:
                    return None
                # os.startfile would be simpler, but use subprocess for explicitness
                return subprocess.Popen([executable])
            else:
                # unix-like
                if self.dry_run:
                    return None
                return subprocess.Popen([executable])
        except FileNotFoundError:
            raise

    def execute(self, command: Command, context=None) -> SkillResult:
        app = command.entities.get("app") or command.entities.get("application") or command.entities.get("path")
        if not app:
            return SkillResult(False, "No app specified to open", {"missing": "app"})

        # Try to resolve executable
        path = shutil.which(app)
        if not path:
            # maybe user passed a known common name; return helpful message
            return SkillResult(False, f"Executable '{app}' not found in PATH. Provide full path or install the app.")

        try:
            proc = self._open_platform(path)
            # If dry_run, proc will be None
            return SkillResult(True, f"Opened {app}", {"pid": getattr(proc, "pid", None)})
        except Exception as exc:
            return SkillResult(False, f"Failed to open {app}: {exc}")
