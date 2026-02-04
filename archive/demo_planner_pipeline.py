# examples/demo_planner_pipeline.py
from kyrax_core.planner_pipeline import plan_validate_and_dispatch
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.context_logger import ContextLogger
from kyrax_core.planner import TaskPlanner
from kyrax_core.command import Command

# Dummy dispatcher that prints and returns a result dict
class DummyDispatcher:
    def dispatch(self, cmd: Command):
        print("DISPATCH ->", cmd)
        return {"ok": True, "intent": cmd.intent, "entities": cmd.entities}


def demo():
    context_logger = ContextLogger()
    # simulate previous command to populate context (e.g., user earlier sent a message)
    sample_cmd = Command(intent="send_message", domain="application", entities={"contact":"Rohit","text":"hi"}, confidence=0.9, source="voice")
    context_logger.update_from_command(sample_cmd)

    dispatcher = DummyDispatcher()
    # example high-level goal that triggers prepare_presentation template
    goal = "Prepare my laptop for a presentation"

    results, issues = plan_validate_and_dispatch(goal_text=goal, dispatcher=dispatcher,
                                                planner=TaskPlanner(), builder=CommandBuilder(),
                                                context_logger=context_logger)
    print("\nRESULTS:", results)
    print("ISSUES:", issues)

if __name__ == "__main__":
    demo()
