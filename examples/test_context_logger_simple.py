# examples/test_context_logger_simple.py
from kyrax_core.context_logger import ContextLogger
from kyrax_core.command import Command

ctx = ContextLogger(max_entries=5, ttl_seconds=3600)

c1 = Command(intent="send_message", domain="application", entities={"contact":"Rohit","app":"whatsapp","text":"hi"}, confidence=0.95, source="voice")
ctx.update_from_command(c1)

# pronoun case
filled = ctx.fill_missing_entities({"contact":"him", "text":"another"}, required_keys=["contact"])
assert filled["contact"] == "Rohit"
print("ok")
