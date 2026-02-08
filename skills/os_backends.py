# skills/os_backends.py
from __future__ import annotations
from typing import Dict, Any
import platform
import shutil
import subprocess
import logging

# Import CalledProcessError locally so catching it doesn't depend on monkeypatched subprocess module
from subprocess import CalledProcessError as _CalledProcessError

log = logging.getLogger(__name__)

class OSBackend:
    def set_volume(self, level: int, dry_run: bool = True) -> Dict[str, Any]:
        raise NotImplementedError
    def mute(self, mute: bool, dry_run: bool = True) -> Dict[str, Any]:
        raise NotImplementedError
    def open_app(self, app: str, dry_run: bool = True) -> Dict[str, Any]:
        raise NotImplementedError
    def power_action(self, action: str, dry_run: bool = True) -> Dict[str, Any]:
        raise NotImplementedError

class WindowsBackend(OSBackend):
    def __init__(self):
        self.platform = "Windows"
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            self._AudioUtilities = AudioUtilities
            self._IAudioEndpointVolume = IAudioEndpointVolume
            self._cast = cast
            self._POINTER = POINTER
            self._CLSCTX_ALL = CLSCTX_ALL
            self.available = True
        except Exception as e:
            log.info("pycaw not available: %s", e)
            self.available = False

    def set_volume(self, level: int, dry_run: bool = True) -> Dict[str, Any]:
        level = max(0, min(100, int(level)))
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "set_volume", "level": level}
        if not self.available:
            return {"ok": False, "error": "pycaw_missing"}
        try:
            dev = self._AudioUtilities.GetSpeakers()
            interface = dev.Activate(self._IAudioEndpointVolume._iid_, self._CLSCTX_ALL, None)
            vol = self._cast(interface, self._POINTER(self._IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(level / 100.0, None)
            current = vol.GetMasterVolumeLevelScalar()
            return {"ok": True, "action": "set_volume", "level": int(round(current * 100))}
        except Exception as e:
            return {"ok": False, "error": "set_volume_failed", "exc": str(e)}

    def mute(self, mute: bool, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "mute", "mute": bool(mute)}
        if not self.available:
            return {"ok": False, "error": "pycaw_missing"}
        try:
            dev = self._AudioUtilities.GetSpeakers()
            interface = dev.Activate(self._IAudioEndpointVolume._iid_, self._CLSCTX_ALL, None)
            vol = self._cast(interface, self._POINTER(self._IAudioEndpointVolume))
            vol.SetMute(1 if mute else 0, None)
            return {"ok": True, "action": "mute", "mute": bool(mute)}
        except Exception as e:
            return {"ok": False, "error": "mute_failed", "exc": str(e)}

    def open_app(self, app: str, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "open_app", "app": app}
        try:
            subprocess.Popen([app], shell=False)
            return {"ok": True, "action": "open_app", "app": app}
        except FileNotFoundError:
            try:
                subprocess.Popen(["start", "", app], shell=True)
                return {"ok": True, "action": "open_app", "app": app}
            except Exception as e:
                return {"ok": False, "error": "open_app_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "open_app_failed", "exc": str(e)}

    def power_action(self, action: str, dry_run: bool = True) -> Dict[str, Any]:
        action = action.lower()
        if dry_run:
            return {"ok": True, "dry_run": True, "action": action}
        try:
            if action in ("shutdown", "poweroff"):
                cmd = ["shutdown", "/s", "/t", "0"]
            elif action == "restart":
                cmd = ["shutdown", "/r", "/t", "0"]
            elif action == "sleep":
                cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"]
            else:
                return {"ok": False, "error": "unknown_action", "action": action}
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd, "stdout": getattr(proc, "stdout", "")}
        except _CalledProcessError as e:
            return {"ok": False, "error": "power_action_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "power_action_failed", "exc": str(e)}

class LinuxBackend(OSBackend):
    def __init__(self):
        self.platform = "Linux"

    def set_volume(self, level: int, dry_run: bool = True) -> Dict[str, Any]:
        level = max(0, min(100, int(level)))
        cmd = ["amixer", "sset", "Master", f"{level}%"]
        if dry_run:
            return {"ok": True, "dry_run": True, "cmd": cmd, "action": "set_volume", "level": level}
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd, "level": level}
        except _CalledProcessError as e:
            return {"ok": False, "error": "amixer_failed", "cmd": cmd, "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "amixer_failed", "cmd": cmd, "exc": str(e)}

    def mute(self, mute: bool, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "mute", "mute": bool(mute)}
        try:
            cmd = ["amixer", "sset", "Master", "mute" if mute else "unmute"]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd}
        except _CalledProcessError as e:
            return {"ok": False, "error": "amixer_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "amixer_failed", "exc": str(e)}

    def open_app(self, app: str, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "open_app", "app": app}
        path = shutil.which(app)
        if path:
            try:
                subprocess.Popen([path])
                return {"ok": True, "cmd": [path]}
            except Exception as e:
                return {"ok": False, "error": "open_app_failed", "exc": str(e)}
        return {"ok": False, "error": "executable_not_found", "app": app}

    def power_action(self, action: str, dry_run: bool = True) -> Dict[str, Any]:
        action = action.lower()
        if dry_run:
            return {"ok": False, "dry_run": True, "error": "power_action_failed", "action": action}
        try:
            if action in ("shutdown", "poweroff"):
                cmd_candidates = [["systemctl", "poweroff"], ["shutdown", "-h", "now"]]
            elif action == "restart":
                cmd_candidates = [["systemctl", "reboot"], ["shutdown", "-r", "now"]]
            elif action == "sleep":
                cmd_candidates = [["systemctl", "suspend"]]
            else:
                return {"ok": False, "error": "unknown_action", "action": action}
            last_err = []
            for cmd in cmd_candidates:
                try:
                    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    return {"ok": True, "cmd": cmd, "stdout": getattr(proc, "stdout", "")}
                except _CalledProcessError as e:
                    last_err.append((cmd, str(e)))
                except FileNotFoundError:
                    last_err.append((cmd, "not_found"))
            return {"ok": False, "error": "all_candidates_failed", "details": last_err}
        except Exception as e:
            return {"ok": False, "error": "power_action_failed", "exc": str(e)}

class MacBackend(OSBackend):
    def __init__(self):
        self.platform = "Darwin"

    def set_volume(self, level: int, dry_run: bool = True) -> Dict[str, Any]:
        level = max(0, min(100, int(level)))
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "set_volume", "level": level}
        try:
            cmd = ["osascript", "-e", f"set volume output volume {level}"]
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd}
        except _CalledProcessError as e:
            return {"ok": False, "error": "osascript_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "osascript_failed", "exc": str(e)}

    def mute(self, mute: bool, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "mute", "mute": bool(mute)}
        try:
            cmd = ["osascript", "-e", f"set volume output muted {'true' if mute else 'false'}"]
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd}
        except _CalledProcessError as e:
            return {"ok": False, "error": "osascript_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "osascript_failed", "exc": str(e)}

    def open_app(self, app: str, dry_run: bool = True) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "action": "open_app", "app": app}
        try:
            cmd = ["open", "-a", app]
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd}
        except _CalledProcessError as e:
            return {"ok": False, "error": "open_app_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "open_app_failed", "exc": str(e)}

    def power_action(self, action: str, dry_run: bool = True) -> Dict[str, Any]:
        action = action.lower()
        if dry_run:
            return {"ok": True, "dry_run": True, "action": action}
        try:
            if action in ("shutdown", "poweroff"):
                cmd = ["osascript","-e","tell app \"System Events\" to shut down"]
            elif action == "restart":
                cmd = ["osascript","-e","tell app \"System Events\" to restart"]
            elif action == "sleep":
                cmd = ["osascript","-e","tell app \"System Events\" to sleep"]
            else:
                return {"ok": False, "error": "unknown_action", "action": action}
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"ok": True, "cmd": cmd}
        except _CalledProcessError as e:
            return {"ok": False, "error": "power_action_failed", "exc": str(e)}
        except Exception as e:
            return {"ok": False, "error": "power_action_failed", "exc": str(e)}

def get_backend_for_current_platform() -> OSBackend:
    sys_plat = platform.system()
    if sys_plat == "Windows":
        return WindowsBackend()
    if sys_plat == "Darwin":
        return MacBackend()
    return LinuxBackend()
