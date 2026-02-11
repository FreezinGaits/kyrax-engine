# kyrax_core/policy_store.py
"""
PolicyStore: load policy (JSON/YAML) from disk and expose getters.
Supports manual reload() for admin UI or hot-reload.
If the config file is missing/invalid, falls back to safe defaults.
"""

import os
import json
import time
from typing import List, Dict, Any
import threading
import logging

log = logging.getLogger(__name__)

try:
    import yaml  # pyyaml if present
except Exception:
    yaml = None

from kyrax_core import config

_default = {
    "ALLOWED_OS_INTENTS": [
        "open_app",
        "close_app",
        "set_volume",
        "mute",
        "unmute",
    ],
    "HIGH_RISK_INTENTS": [
        "shutdown",
        "restart",
        "sleep",
        "factory_reset"
    ],
    "INTENT_ROLE_REQUIREMENTS": {
        "shutdown": ["admin"],
        "restart": ["admin"],
        "sleep": ["admin"]
    },
    # other policy keys may be added
}

class PolicyStore:
    def __init__(self, path: str = None):
        self.path = path or config.KYRAX_POLICY_PATH
        self._lock = threading.RLock()
        self._mtime = 0.0
        self._policy: Dict[str, Any] = {}
        self.reload()  # load at startup

    def _read_file(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            mtime = os.path.getmtime(self.path)
            if mtime <= self._mtime:
                return {}  # no change
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
            if self.path.lower().endswith((".yml", ".yaml")) and yaml:
                return yaml.safe_load(text) or {}
            try:
                return json.loads(text)
            except Exception:
                if yaml:
                    return yaml.safe_load(text) or {}
                raise
        except Exception as e:
            log.warning("PolicyStore load error: %s", e)
            return {}

    def reload(self) -> None:
        with self._lock:
            data = self._read_file()
            if data:
                self._policy = data
                try:
                    self._mtime = os.path.getmtime(self.path)
                except Exception:
                    self._mtime = time.time()
                log.info("PolicyStore: loaded policy from %s", self.path)
                return
            # else fallback
            if not self._policy:
                self._policy = _default.copy()

    # Accessors
    def get_allowed_os_intents(self) -> List[str]:
        return list(self._policy.get("ALLOWED_OS_INTENTS", _default["ALLOWED_OS_INTENTS"]))

    def get_high_risk_intents(self) -> List[str]:
        return list(self._policy.get("HIGH_RISK_INTENTS", _default["HIGH_RISK_INTENTS"]))

    def get_intent_role_requirements(self) -> Dict[str, List[str]]:
        return dict(self._policy.get("INTENT_ROLE_REQUIREMENTS", _default["INTENT_ROLE_REQUIREMENTS"]))

# module-level singleton for easy imports
_store = None

def get_policy_store() -> PolicyStore:
    global _store
    if _store is None:
        _store = PolicyStore()
    return _store
