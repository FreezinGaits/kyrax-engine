# examples/test_command.py
from kyrax_core.intent_mapper import map_nlu_to_command

# hypothetical NLU output
nlu = {
    "intent": "send_message",
    "slots": {"contact": "Rohit", "message": "Hey, I'll be late", "app": "whatsapp"},
    "confidence": 0.94,
    "meta": {"source": "whisper"}
}
# If needed to show an academic schema:
# {
#   "$schema": "http://json-schema.org/draft-07/schema#",
#   "title": "KYRAX Command",
#   "type": "object",
#   "properties": {
#     "intent": {"type": "string"},
#     "domain": {"type": "string"},
#     "entities": {"type": "object"},
#     "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
#     "source": {"type": "string"},
#     "context_id": {"type": ["string", "null"]},
#     "meta": {"type": "object"}
#   },
#   "required": ["intent", "domain", "entities"]
# }


cmd = map_nlu_to_command(nlu, source="voice")
print(cmd)
print("JSON:", cmd.to_json())

assert cmd.intent == "send_message"
assert cmd.domain == "application"
assert cmd.get("contact") == "Rohit"
assert cmd.get("text") == "Hey, I'll be late"
