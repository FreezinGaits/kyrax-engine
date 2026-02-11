# kyrax_core/config.py
"""
Central runtime configuration for KYRAX.
Simple, environment-variable-driven defaults. Import wherever you need
global thresholds or feature flags.
"""

import os
from typing import Any

def _env_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(int(default))).lower() in ("1", "true", "yes")

# Does the system allow performing real destructive power actions?
# Default: false (safe)
KYRAX_ALLOW_REAL_POWER_ACTIONS = _env_bool("KYRAX_ALLOW_REAL_POWER_ACTIONS", False)

# A lower-level override used only for tests to force dry-run behavior.
KYRAX_FORCE_DRY_RUN = _env_bool("KYRAX_FORCE_DRY_RUN", False)

# LLM confidence threshold for accepting an automatic mapping (0.0 - 1.0)
LLM_CONFIDENCE_THRESHOLD = float(os.environ.get("KYRAX_LLM_CONFIDENCE", "0.7"))

# Redis URL for rate limiter (optional)
REDIS_URL = os.environ.get("KYRAX_REDIS_URL", "redis://localhost:6379/0")

# Path to policy file (JSON or YAML). If absent, policy_store falls back to built-ins.
KYRAX_POLICY_PATH = os.environ.get("KYRAX_POLICY_PATH", "config/policy.yaml")

# Audit log path
KYRAX_AUDIT_LOG = os.environ.get("KYRAX_AUDIT_LOG", "kyrax_audit.log")

# Confidence threshold default for LLM outputs (if used)
KYRAX_CONFIDENCE_THRESHOLD: float = float(os.environ.get("KYRAX_CONFIDENCE_THRESHOLD", "0.7"))