# kyrax_core/audit.py
"""
Simple append-only audit logger for guard decisions and executed commands.
In production, use a proper audit DB (append-only) and secure the logs.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict

AUDIT_FILE = os.environ.get("KYRAX_AUDIT_FILE", "kyrax_audit.log")

def audit_record(record: Dict[str, Any]):
    rec = {
        "ts": datetime.utcnow().isoformat() + "Z",
        **record
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
