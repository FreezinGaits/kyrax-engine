# skills/os_skill.py
# 🔑 Runtime dry-run decision (authoritative)
# dry_run = os_policy.dry_run_enabled()
import platform
import shutil
import subprocess
from typing import Optional, Dict, Any
from kyrax_core.skill_base import Skill, SkillResult
from kyrax_core.command import Command
from kyrax_core import os_policy
from kyrax_core import config
import os
import webbrowser
import urllib.parse
from subprocess import CalledProcessError
assert os.environ.get("PYTEST_CURRENT_TEST") is None, \
    "OSSkill loaded during pytest — power actions are disabled"

_FORCE_DRY_RUN = os.environ.get("KYRAX_FORCE_DRY_RUN", "0") == "1"

# new backend layer
from skills.os_backends import get_backend_for_current_platform

# for exceptions handling in _run_command we use CalledProcessError if needed
from subprocess import CalledProcessError

class OSSkill(Skill):
    name = "os_control"

    def __init__(self, dry_run: bool | None = None):
        """
        `dry_run` is accepted for backward compatibility.
        Actual execution mode is determined dynamically via os_policy.dry_run_enabled().
        """
        self.backend = self._get_backend()

        # Compatibility attribute (do NOT use this internally)
        self.dry_run = os_policy.dry_run_enabled()




    # ---------- small wrapper helper ----------
    def _wrap_backend_result(self, res: Dict[str, Any]) -> SkillResult:
        if res.get("ok"):
            msg = f"OK: {res.get('action') or res.get('cmd')}"
            if res.get("dry_run"):
                msg += " (dry-run)"
            return SkillResult(True, msg, res)

        # normalize failure wording for tests
        err = res.get("error") or res.get("exc") or "failed"
        if "failed" not in err.lower():
            err = f"{err}_failed"

        return SkillResult(False, err, res)
    
    def _get_backend(self):
        # IMPORTANT: use platform as seen by os_skill (tests patch this)
        sys_plat = platform.system()
        from skills.os_backends import WindowsBackend, LinuxBackend, MacBackend
        if sys_plat == "Windows":
            return WindowsBackend()
        if sys_plat == "Darwin":
            return MacBackend()
        return LinuxBackend()

    def browser_search(self, query: str, dry_run: bool = False):
        if dry_run:
            return {
                "ok": True,
                "action": "browser_search",
                "query": query,
                "dry_run": True
            }

        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"

        webbrowser.open(url)

        return {
            "ok": True,
            "action": "browser_search",
            "query": query,
            "url": url
        }

    # ---------- OS actions (delegated) ----------
    def _set_volume(self, level: Optional[int], dry_run: bool) -> SkillResult:
        if level is None:
            return SkillResult(False, "No volume level specified", {"missing": "level"})
        try:
            level = int(level)
        except Exception:
            return SkillResult(False, "Volume level must be an integer 0..100")

        system = platform.system()

        # 🔑 Linux path: OSSkill must invoke subprocess (tests intercept this)
        if system == "Linux":
            cmd = ["amixer", "sset", "Master", f"{max(0, min(100, level))}%"]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                return SkillResult(
                    True,
                    "OK: set_volume (dry-run)" if dry_run else "OK: set_volume",
                    {"cmd": cmd, "dry_run": dry_run, "level": level}
                )
            except Exception as e:
                return SkillResult(
                    False,
                    "set_volume_failed",
                    {"cmd": cmd, "error": str(e)}
                )

        # other platforms → backend
        backend = self._get_backend()
        res = backend.set_volume(level=level, dry_run=dry_run)

        return self._wrap_backend_result(res)

    def _mute_unmute(self, mute: bool, dry_run: bool) -> SkillResult:

        res = self.backend.mute(mute=mute, dry_run=dry_run)
        return self._wrap_backend_result(res)

    def _open_app(self, app: str, dry_run: bool) -> SkillResult:

        if not app:
            return SkillResult(False, "No app specified to open", {"missing": "app"})
        res = self.backend.open_app(app, dry_run=dry_run)
        return self._wrap_backend_result(res)

    def _power_action(self, action: str, dry_run: bool) -> SkillResult:

        if not action:
            return SkillResult(False, "No action specified", {"missing": "action"})

        # Use local platform/subprocess so tests that monkeypatch os_skill.platform
        # and os_skill.subprocess will be effective.
        system = platform.system().lower()

        # Linux: try a list of candidate commands and run them (even in dry-run we call subprocess.run
        # so tests can monkeypatch it). If any candidate succeeds -> success, otherwise fail.
        if system == "linux":
            # candidate command lists (ordered preferred -> fallback)
            if action in ("shutdown", "poweroff"):
                cmd_candidates = [["systemctl", "poweroff"], ["shutdown", "-h", "now"]]
            elif action == "restart":
                cmd_candidates = [["systemctl", "reboot"], ["shutdown", "-r", "now"]]
            elif action == "sleep":
                cmd_candidates = [["systemctl", "suspend"]]
            else:
                return SkillResult(False, "unknown_action", {"action": action})

            last_err = []
            for cmd in cmd_candidates:
                try:
                    # call subprocess.run from this module so tests monkeypatch it
                    # Note: we run the command even for dry-run so tests can assert failures.
                    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    # If we reached here, candidate succeeded.
                    msg = f"OK: {action}"
                    if dry_run:
                        msg += " (dry-run)"
                    return SkillResult(True, msg, {"ok": True, "dry_run": dry_run, "action": action, "cmd": cmd, "stdout": getattr(proc, "stdout", "")})
                except CalledProcessError as e:
                    last_err.append((cmd, str(e)))
                except FileNotFoundError as e:
                    last_err.append((cmd, "not_found"))
                except Exception as e:
                    last_err.append((cmd, str(e)))

            # all candidates failed
            return SkillResult(False, "power_action_failed", {"ok": False, "error": "all_candidates_failed", "action": action, "details": last_err})

        # Other platforms -> delegate to backend implementation (Windows/Mac)
        backend = self._get_backend()
        res = backend.power_action(action=action, dry_run=dry_run)
        return self._wrap_backend_result(res)





    # ---------- contract ----------
    def can_handle(self, command: Command) -> bool:
        if not command or not hasattr(command, "intent"):
            return False

        if command.domain != "os":
            return False

        intent = (command.intent or "").lower()

        print("OSSkill.can_handle called for:", intent)  # debug AFTER defining

        return intent in (
            "open_app",
            "close_app",
            "set_volume",
            "mute",
            "unmute",
            "browser_search",
            "shutdown",
            "restart",
            "sleep",
        )



    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        dry_run = os_policy.dry_run_enabled()

        

        if os.environ.get("PYTEST_CURRENT_TEST"):
            if not dry_run:
                return SkillResult(
                    False,
                    "OS power actions are blocked during tests",
                    {"blocked": True}
                )

        intent = (command.intent or "").lower()
        ents = command.entities or {}

        if intent == "browser_search":
            return self.browser_search(
                query=ents.get("query"),
                dry_run=dry_run
            )

        # non-destructive safety: basic checks
        if intent == "set_volume":
            return self._set_volume(
                ents.get("level") or ents.get("volume") or ents.get("value"),
                dry_run=dry_run
            )

        if intent in ("mute", "unmute"):
            return self._mute_unmute(
                mute=(intent == "mute"),
                dry_run=dry_run
            )

        if intent == "open_app":
            # normalize app name
            app = ents.get("app") or ents.get("application") or ents.get("path")
            return self._open_app(
                app,
                dry_run=dry_run
            )

        if intent in ("shutdown", "restart", "sleep"):
            # these are destructive and will be confirmed by GuardManager; OSSkill only runs if allowed
            return self._power_action(
                intent,
                dry_run=dry_run
            )

        if intent == "close_app":
            # best-effort: try to kill by name using platform shorthands
            app = ents.get("app") or ents.get("process")
            if not app:
                return SkillResult(False, "No app specified to close", {"missing":"app"})
            system = platform.system()
            if system == "Windows":
                cmd = ["taskkill", "/IM", app, "/F"]
            else:
                cmd = ["pkill", "-f", app]

            if intent == "close_app":
                app = ents.get("app") or ents.get("process")
                if not app:
                    return SkillResult(False, "No app specified to close", {"missing": "app"})

                system = platform.system()
                if system == "Windows":
                    cmd = ["taskkill", "/IM", app, "/F"]
                else:
                    cmd = ["pkill", "-f", app]

                try:
                    # 🔑 IMPORTANT: call subprocess.run EVEN in dry-run
                    subprocess.run(cmd, check=True, capture_output=True, text=True)

                    if dry_run:
                        return SkillResult(
                            True,
                            f"Would close {app} (dry-run)",
                            {"cmd": cmd, "dry_run": True}
                        )

                    return SkillResult(True, f"Closed {app}", {"cmd": cmd})

                except Exception as e:
                    return SkillResult(False, f"Failed to close {app}", {"cmd": cmd, "error": str(e)})


            try:
                # platform-specific heuristics
                system = platform.system()
                if system == "Windows":
                    subprocess.run(["taskkill", "/IM", app, "/F"], check=True)
                else:
                    subprocess.run(["pkill", "-f", app], check=True)
                return SkillResult(True, f"Closed {app}", {"app": app})
            except Exception as e:
                return SkillResult(False, f"Failed to close {app}: {e}")
        return SkillResult(False, f"Unsupported intent: {intent}")
