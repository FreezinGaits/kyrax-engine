# kyrax_core/workflow_manager.py
"""
Workflow and state manager for KYRAX Phase-3.

Provides:
 - Workflow: a persistent workflow object (goal + ordered steps)
 - Step: per-command step with status and result
 - WorkflowStore: simple SQLite-backed persistence + helpers
 - Execution hooks: helper functions to integrate with your dispatcher/chain executor
"""

import sqlite3
import json
import uuid
import datetime
import threading
from typing import List, Dict, Any, Optional, Tuple
from kyrax_core.command import Command

# step status constants
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

# ---------------------------
# Models (lightweight dict wrappers)
# ---------------------------
class Step:
    def __init__(self, step_id: Optional[str] = None, command: Optional[Command] = None):
        self.step_id = step_id or str(uuid.uuid4())
        self.command = command  # Command instance
        self.status = STATUS_PENDING
        self.attempts = 0
        self.last_error: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self.created_at = _now_iso()
        self.updated_at = self.created_at

    def to_row(self) -> Tuple[str, str, str, int, Optional[str], Optional[str], str]:
        """Return tuple matching DB columns (without workflow_id)."""
        cmd_json = self.command.to_json() if self.command else "{}"
        result_json = json.dumps(self.result, ensure_ascii=False) if self.result is not None else None
        return (self.step_id, cmd_json, self.status, self.attempts, self.last_error, result_json, self.updated_at)

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Step":
        s = Step(step_id=row["step_id"],
                 command=Command.from_json(row["command_json"]) if row["command_json"] else Command(intent="unknown", domain="generic"))
        s.status = row["status"]
        s.attempts = int(row["attempts"] or 0)
        s.last_error = row["last_error"]
        s.result = json.loads(row["result_json"]) if row["result_json"] else None
        s.created_at = row["created_at"]
        s.updated_at = row["updated_at"]
        return s

class Workflow:
    def __init__(self, workflow_id: Optional[str] = None, goal: str = ""):
        self.workflow_id = workflow_id or str(uuid.uuid4())
        self.goal = goal
        self.state = "active"  # active / completed / failed / paused
        self.created_at = _now_iso()
        self.updated_at = self.created_at

    def to_row(self) -> Tuple[str, str, str, str]:
        return (self.workflow_id, self.goal, self.state, self.updated_at)

# ---------------------------
# WorkflowStore: SQLite persistence
# ---------------------------
class WorkflowStore:
    """
    Small SQLite-backed workflow storage.

    Schema:
      workflows(workflow_id PK, goal, state, created_at, updated_at)
      steps(step_id PK, workflow_id FK, command_json, status, attempts, last_error, result_json, created_at, updated_at)
    """

    def __init__(self, path: str = "kyrax_workflows.db"):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                goal TEXT,
                state TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                step_id TEXT PRIMARY KEY,
                workflow_id TEXT,
                command_json TEXT,
                status TEXT,
                attempts INTEGER,
                last_error TEXT,
                result_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id)
            )
            """)
            self._conn.commit()

    def create_workflow(self, goal: str, commands: List[Command]) -> str:
        """
        Create workflow + steps from an ordered list of Command objects.
        Returns workflow_id.
        """
        wf = Workflow(goal=goal)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("INSERT INTO workflows (workflow_id, goal, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (wf.workflow_id, wf.goal, wf.state, wf.created_at, wf.updated_at))
            now = _now_iso()
            for cmd in commands:
                step = Step(command=cmd)
                cur.execute("""
                    INSERT INTO steps (step_id, workflow_id, command_json, status, attempts, last_error, result_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (step.step_id, wf.workflow_id, cmd.to_json(), step.status, step.attempts, step.last_error, None, step.created_at, step.updated_at))
            self._conn.commit()
        return wf.workflow_id

    def list_active_workflows(self) -> List[Workflow]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM workflows WHERE state = 'active'")
            return [Workflow(workflow_id=r["workflow_id"], goal=r["goal"]) for r in cur.fetchall()]

    def get_workflow(self, workflow_id: str) -> Tuple[Workflow, List[Step]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,))
            r = cur.fetchone()
            if not r:
                raise KeyError("workflow_not_found")
            wf = Workflow(workflow_id=r["workflow_id"], goal=r["goal"])
            wf.state = r["state"]
            wf.created_at = r["created_at"]
            wf.updated_at = r["updated_at"]
            cur.execute("SELECT * FROM steps WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,))
            steps = [Step.from_row(row) for row in cur.fetchall()]
            return wf, steps

    def _update_step_row(self, step: Step, workflow_id: str):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
                UPDATE steps SET status=?, attempts=?, last_error=?, result_json=?, updated_at=?
                WHERE step_id=? AND workflow_id=?
            """, (step.status, step.attempts, step.last_error, json.dumps(step.result, ensure_ascii=False) if step.result is not None else None, step.updated_at, step.step_id, workflow_id))
            self._conn.commit()

    def mark_step_in_progress(self, workflow_id: str, step_id: str):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE steps SET status=?, updated_at=? WHERE step_id=? AND workflow_id=?", (STATUS_IN_PROGRESS, _now_iso(), step_id, workflow_id))
            self._conn.commit()

    def mark_step_completed(self, workflow_id: str, step_id: str, result: Optional[Dict[str, Any]] = None):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM steps WHERE step_id=? AND workflow_id=?", (step_id, workflow_id))
            r = cur.fetchone()
            if not r:
                raise KeyError("step_not_found")
            step = Step.from_row(r)
            step.status = STATUS_COMPLETED
            step.attempts += 1
            step.result = result
            step.last_error = None
            step.updated_at = _now_iso()
            self._update_step_row(step, workflow_id)

    def mark_step_failed(self, workflow_id: str, step_id: str, error: str):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM steps WHERE step_id=? AND workflow_id=?", (step_id, workflow_id))
            r = cur.fetchone()
            if not r:
                raise KeyError("step_not_found")
            step = Step.from_row(r)
            step.status = STATUS_FAILED
            step.attempts += 1
            step.last_error = str(error)
            step.updated_at = _now_iso()
            self._update_step_row(step, workflow_id)

    def retry_step(self, workflow_id: str, step_id: str):
        """Reset a failed step back to pending (increment attempts remains tracked when executed)."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE steps SET status=?, last_error=NULL, updated_at=? WHERE step_id=? AND workflow_id=?",
                        (STATUS_PENDING, _now_iso(), step_id, workflow_id))
            self._conn.commit()

    def mark_workflow_state(self, workflow_id: str, state: str):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE workflows SET state=?, updated_at=? WHERE workflow_id=?", (state, _now_iso(), workflow_id))
            self._conn.commit()

    # Convenience helpers
    def get_next_pending_step(self, workflow_id: str) -> Optional[Step]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM steps WHERE workflow_id=? AND status IN (?, ?) ORDER BY created_at ASC LIMIT 1",
                        (workflow_id, STATUS_PENDING, STATUS_FAILED))
            r = cur.fetchone()
            return Step.from_row(r) if r else None

    def get_all_steps(self, workflow_id: str) -> List[Step]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM steps WHERE workflow_id=? ORDER BY created_at ASC", (workflow_id,))
            return [Step.from_row(r) for r in cur.fetchall()]

    def explain_workflow(self, workflow_id: str) -> Dict[str, Any]:
        wf, steps = self.get_workflow(workflow_id)
        summary = {
            "workflow_id": wf.workflow_id,
            "goal": wf.goal,
            "state": wf.state,
            "created_at": wf.created_at,
            "updated_at": wf.updated_at,
            "steps": []
        }
        for st in steps:
            summary["steps"].append({
                "step_id": st.step_id,
                "intent": st.command.intent,
                "domain": st.command.domain,
                "status": st.status,
                "attempts": st.attempts,
                "last_error": st.last_error,
                "result": st.result,
                "updated_at": st.updated_at
            })
        return summary

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
