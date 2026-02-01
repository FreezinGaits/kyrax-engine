# examples/demo_planner.py
from kyrax_core.planner import TaskPlanner
from kyrax_core.command import Command
import json

# tiny dispatcher stub for demo. Replace with your real Executor/Dispatcher.
class DummyDispatcher:
    def dispatch(self, cmd: Command):
        # Pretend to execute and return a simple result dict.
        print("-> Dispatching:", cmd)
        return {"ok": True, "intent": cmd.intent, "entities": cmd.entities}

def pretty_print_commands(cmds):
    for i, c in enumerate(cmds, 1):
        print(f"{i}. {c.intent}  domain={c.domain}  entities={c.entities}  src={c.source}")
        print("   json:", c.to_json())

def demo():
    planner = TaskPlanner() 
    dispatcher = DummyDispatcher()

    goals = [
        "Prepare my laptop for a presentation",
        "Set volume to 30 and enable do not disturb",
        "Open talk_v2.pptx and start slideshow"
    ]

    # simulate a context where user recently used 'talk_v2.pptx'
    context = {"last_file": "talk_v2.pptx", "presentation_file": "talk_v2.pptx"}

    for g in goals:
        print("\nGOAL:", g)
        plan = planner.plan(g, context=context)
        print("PLAN:")
        pretty_print_commands(plan)

        print("\nExecuting plan (dummy dispatcher):")
        results = planner.execute_plan(plan, dispatcher)
        print("Results:", json.dumps(results, indent=2))

if __name__ == "__main__":
    demo()
