# kyrax_core/audit.py
"""
Simple append-only audit logger for guard decisions and executed commands.
In production, use a proper audit DB (append-only) and secure the logs.
"""

# import json
# import os
# from datetime import datetime
# from typing import Any, Dict

# AUDIT_FILE = os.environ.get("KYRAX_AUDIT_FILE", "kyrax_audit.log")

# def audit_record(record: Dict[str, Any]):
#     rec = {
#         "ts": datetime.utcnow().isoformat() + "Z",
#         **record
#     }
#     with open(AUDIT_FILE, "a", encoding="utf-8") as f:
#         f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# kyrax_core/audit.py
"""
Simple append-only audit log with SHA256 chaining.
Each line is a JSON object with fields:
  ts, event_type, payload, prev_hash, hash

This is not a full tamper-proof ledger but provides tamper-evidence
for simple deployments. For production, ship to an immutable store or WORM.
"""

import json
import hashlib
import time
import threading
from typing import Dict, Any
from kyrax_core import config

_lock = threading.Lock()

def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _compute_hash(prev_hash: str, record_json: str) -> str:
    m = hashlib.sha256()
    m.update((prev_hash or "").encode("utf-8"))
    m.update(record_json.encode("utf-8"))
    return m.hexdigest()

def _last_hash_from_file(path: str) -> str:
    try:
        with open(path, "rb") as f:
            # iterate backwards to find last non-empty line
            last = None
            for line in f:
                if line.strip():
                    last = line
            if not last:
                return ""
            rec = json.loads(last.decode("utf-8"))
            return rec.get("hash", "")
    except Exception:
        return ""

def record(event_type: str, payload: Dict[str, Any]) -> None:
    path = config.KYRAX_AUDIT_LOG
    entry = {
        "ts": _now_iso(),
        "event_type": event_type,
        "payload": payload,
    }
    rec_json = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    with _lock:
        prev = _last_hash_from_file(path)
        h = _compute_hash(prev, rec_json)
        out = {"ts": entry["ts"], "event_type": event_type, "payload": payload, "prev_hash": prev, "hash": h}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
