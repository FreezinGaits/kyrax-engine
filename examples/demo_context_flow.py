# examples/demo_context_flow.py
from kyrax_core.nlu.nlu_engine import NLUEngine
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.context_logger import ContextLogger

nlu = NLUEngine()
builder = CommandBuilder()
ctx = ContextLogger(max_entries=20, ttl_seconds=600)

# 1) user: "Send hi to Rohit on WhatsApp"
s1 = "Send hi to Rohit on WhatsApp"
nlu1 = nlu.analyze(s1)
cmd1, issues1 = builder.build(nlu1, source="voice", context_logger=ctx)
print("1:", nlu1, issues1, cmd1)
# ctx now updated

# 2) follow-up: "Send him another one"
s2 = "Send him another one"
nlu2 = nlu.analyze(s2)
cmd2, issues2 = builder.build(nlu2, source="voice", context_logger=ctx)
print("2:", nlu2, issues2, cmd2)
# expect cmd2.entities['contact'] == "Rohit"


