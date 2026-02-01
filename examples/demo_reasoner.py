# examples/demo_reasoner.py
"""
Demo: show how to use AIReasoner -> CommandBuilder -> (Planner/Dispatcher)
This example uses no real LLM; it demonstrates the flow and shows validation.
"""

from kyrax_core.ai_reasoner import AIReasoner
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.nlu.nlu_engine import NLUEngine

def demo():
    reasoner = AIReasoner(llm=None)  # pass a callable to use a real LLM
    builder = CommandBuilder()
    nlu = NLUEngine()

    goal = "Send the report like last time"
    context = {"last_contact": "Rohit", "last_report_url": "https://example.com/finance_report.pdf"}

    proposals = reasoner.suggest_plans(goal, context=context, n=2)
    for p in proposals:
        print("PROPOSAL:", p.explanation, "score=", p.score)
        for i, step in enumerate(p.proposed_commands):
            print(f"  STEP {i+1}: intent={step.intent}, entities={step.entities}, note={step.note}")

    # Validate the top proposal with CommandBuilder
    chosen = proposals[0]
    validated = reasoner.propose_and_validate_plan(goal, context, command_builder=builder, max_candidates=1)
    plan, validated_steps = validated[0]
    print("\nValidated Plan:")
    for cmd_obj, issues in validated_steps:
        print("  CMD:", cmd_obj)
        print("  ISSUES:", issues)

if __name__ == "__main__":
    demo()