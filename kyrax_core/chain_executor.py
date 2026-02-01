# kyrax_core/chain_executor.py
from typing import List, Dict, Any, Tuple, Optional
import re
from kyrax_core.command import Command

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

class ChainExecutionError(Exception):
    pass

class ChainExecutor:
    """
    Execute a sequence of Command objects sequentially (skill-chaining).
    Allows later commands to reference results from earlier ones using placeholders.

    Placeholder syntax (in entity string values):
      {{ last.some_key }}        -> value from last step's result dict
      {{ steps.0.some_key }}     -> value from step index 0's result dict
      {{ steps.1 }}              -> entire step 1 result (stringified)
      {{ global.some_key }}      -> reserved: user-provided global context (optional)

    Behaviour:
      - Executes commands in order via dispatcher.dispatch(command) which should return dict-like result.
      - After each step, stores the returned result in the outputs list.
      - Before dispatching a command, resolves placeholders in its entities using prior outputs.
      - Returns (results_list, issues_list).
    """

    def __init__(self, global_ctx: Optional[Dict[str, Any]] = None):
        self.global_ctx = global_ctx or {}

    # ---------- placeholder rendering ----------
    def _resolve_token(self, token: str, outputs: List[Dict[str, Any]]) -> Optional[Any]:
        """
        Resolve a token like 'last.file_path', 'steps.0.file_path', 'global.foo'
        Returns None if cannot resolve.
        """
        parts = token.split(".")
        if not parts:
            return None
        if parts[0] == "last":
            if not outputs:
                return None
            obj = outputs[-1]
            for p in parts[1:]:
                if isinstance(obj, dict) and p in obj:
                    obj = obj[p]
                else:
                    return None
            return obj
        if parts[0] == "steps":
            if len(parts) < 2:
                return None
            try:
                idx = int(parts[1])
            except ValueError:
                return None
            if idx < 0 or idx >= len(outputs):
                return None
            obj = outputs[idx]
            for p in parts[2:]:
                if isinstance(obj, dict) and p in obj:
                    obj = obj[p]
                else:
                    return None
            return obj
        if parts[0] == "global":
            obj = self.global_ctx
            for p in parts[1:]:
                if isinstance(obj, dict) and p in obj:
                    obj = obj[p]
                else:
                    return None
            return obj
        # unknown token type
        return None

    def _render_value(self, value: Any, outputs: List[Dict[str, Any]]) -> Tuple[Any, List[str]]:
        """
        Recursively render placeholders in strings, dicts, lists.
        Returns (rendered_value, unresolved_placeholders)
        """
        issues: List[str] = []
        if isinstance(value, str):
            def _replace(m):
                token = m.group(1).strip()
                resolved = self._resolve_token(token, outputs)
                if resolved is None:
                    issues.append(token)
                    return m.group(0)  # keep as-is for visibility
                # convert non-str to str for substitution; caller may expect raw type, but we keep string substitution
                if isinstance(resolved, (dict, list)):
                    # JSON-like render for complex objects
                    import json
                    return json.dumps(resolved, ensure_ascii=False)
                return str(resolved)

            new_val = PLACEHOLDER_RE.sub(_replace, value)
            return new_val, issues

        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                rv, iss = self._render_value(v, outputs)
                out[k] = rv
                issues.extend(iss)
            return out, issues

        if isinstance(value, list):
            out_list = []
            for it in value:
                rv, iss = self._render_value(it, outputs)
                out_list.append(rv)
                issues.extend(iss)
            return out_list, issues

        # other scalar types remain unchanged
        return value, []

    def _render_entities(self, entities: Dict[str, Any], outputs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        out = {}
        issues: List[str] = []
        for k, v in (entities or {}).items():
            rv, iss = self._render_value(v, outputs)
            out[k] = rv
            issues.extend(iss)
        return out, issues

    # ---------- chain execution ----------
    def execute_chain(self, commands: List[Command], dispatcher, stop_on_error: bool = True
                     ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Execute commands sequentially.
        dispatcher must implement: dispatch(command: Command) -> dict-like result
        Returns: (results_list, issues_list)
          results_list: list of step results (dicts)
          issues_list: list of issue records: {"step": idx, "command": cmd.to_dict(), "issues": [...], "error": optional}
        """
        outputs: List[Dict[str, Any]] = []
        issues: List[Dict[str, Any]] = []

        for idx, cmd in enumerate(commands):
            # 1) render placeholders in entities from previous outputs
            rendered_entities, render_issues = self._render_entities(cmd.entities or {}, outputs)
            if render_issues:
                issues.append({"step": idx, "command": cmd.to_dict() if hasattr(cmd, "to_dict") else repr(cmd), "issues": [f"unresolved_placeholders:{t}" for t in render_issues]})
                # decide: continue (with placeholders kept) or stop. We'll attempt to continue but mark issue
            # build new command copy (do not mutate original)
            cmd_copy = Command(
                intent=cmd.intent,
                domain=cmd.domain,
                entities=rendered_entities,
                confidence=cmd.confidence,
                source=cmd.source,
                context_id=cmd.context_id,
                meta=cmd.meta.copy() if isinstance(cmd.meta, dict) else cmd.meta
            )

            # 2) dispatch
            try:
                result = dispatcher.dispatch(cmd_copy)
                # normalize result: prefer dict-like
                if result is None:
                    result = {}
                if not isinstance(result, dict):
                    # try to coerce to dict
                    result = {"result": result}
                outputs.append(result)
            except Exception as e:
                issues.append({"step": idx, "command": cmd_copy.to_dict() if hasattr(cmd_copy, "to_dict") else repr(cmd_copy), "issues": [f"dispatch_exception:{e}"]})
                if stop_on_error:
                    break
                else:
                    outputs.append({"error": str(e)})
                    continue

        return outputs, issues
