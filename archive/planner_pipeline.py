# kyrax_core/planner_pipeline.py
from typing import List, Dict, Any, Optional, Tuple
from .planner import TaskPlanner
from .command_builder import CommandBuilder
from .context_logger import ContextLogger
from .command import Command
from kyrax_core.chain_executor import ChainExecutor

# Type-hinted protocol for dispatcher: anything implementing dispatch(command) works.
class DispatcherProtocol:
    def dispatch(self, cmd: Command) -> Any:
        raise NotImplementedError


def build_context_dict_from_logger(ctx_logger: Optional[ContextLogger]) -> Dict[str, Any]:
    """
    Convert context logger state into a simple context dict planner can use.
    Add keys you need (last_file, last_contact, last_app, etc).
    """
    if not ctx_logger:
        return {}
    return {
        "last_file": ctx_logger.get_most_recent("last_file"),
        "presentation_file": ctx_logger.get_most_recent("last_file"),
        "last_contact": ctx_logger.get_most_recent("last_contact"),
        "last_app": ctx_logger.get_most_recent("last_app"),
        "last_device": ctx_logger.get_most_recent("last_device"),
        # snapshot fallback
        "snapshot": ctx_logger.snapshot()
    }


def plan_validate_and_dispatch(
    goal_text: str,
    dispatcher: DispatcherProtocol,
    planner: Optional[TaskPlanner] = None,
    builder: Optional[CommandBuilder] = None,
    context_logger: Optional[ContextLogger] = None,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    End-to-end helper:
      1. Plan -> list[Command]
      2. For each planned Command, run CommandBuilder to validate/normalize (uses context_logger)
      3. If builder returns issues, try a single automatic patch using context_logger where possible
      4. Dispatch validated commands with dispatcher.dispatch(command)
    Returns: (results_list, issues_list)
    Each issue item is {'command': cmd.to_dict(), 'issues': issues}
    """
    planner = planner or TaskPlanner()
    builder = builder or CommandBuilder()
    # prepare context for planner
    context = build_context_dict_from_logger(context_logger)
    results: List[Any] = []
    issues_report: List[Dict[str, Any]] = []

    # 1) plan
    planned_commands: List[Command] = planner.plan(goal_text, context=context)

    chain_executor = ChainExecutor(global_ctx={})
    results, issues = chain_executor.execute_chain(planned_commands, dispatcher)

    # 2) iterate, validate, optionally patch, dispatch
    for planned_cmd in planned_commands:
        # convert planned command into NLU-like dict for CommandBuilder
        nlu_like = {
            "intent": planned_cmd.intent,
            "entities": planned_cmd.entities or {},
            "confidence": planned_cmd.confidence,
            "source": planned_cmd.source or "planner"
        }

        validated_cmd, issues = builder.build(nlu_like, source=planned_cmd.source, context_logger=context_logger)

        # If builder returned issues and no command, attempt a single automatic patch:
        if validated_cmd is None and issues:
            # Attempt to patch missing entities from context_logger heuristics
            patched_entities = dict(planned_cmd.entities or {})
            if context_logger:
                # for each missing_required_entity:<key> try fill
                for iss in issues:
                    if iss.startswith("missing_required_entity:"):
                        key = iss.split(":", 1)[1]
                        candidate = context_logger.get_most_recent(f"last_{key}")
                        if candidate:
                            patched_entities[key] = candidate
                # re-run builder with patched entities
            nlu_like["entities"] = patched_entities
            validated_cmd, issues = builder.build(nlu_like, source=planned_cmd.source, context_logger=context_logger)

        # If still no validated command -> record issue and skip dispatch (caller could ask user)
        if validated_cmd is None:
            issues_report.append({"command": nlu_like, "issues": issues})
            continue

        # Dispatch and collect results (dispatcher should return something)
        try:
            res = dispatcher.execute(validated_cmd)
            results.append(res)
        except Exception as e:
            # record error as an issue and continue
            issues_report.append({"command": validated_cmd.to_dict(), "issues": [f"dispatch_error:{e}"]})

    return results, issues_report
