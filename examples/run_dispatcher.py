# examples/run_dispatcher.py
"""
Run this from the project root:

python -m examples.run_dispatcher

This demonstrates:
- Creating Command objects (manually via intent mapper)
- Registering skills
- Dispatching commands via Dispatcher
- Receiving SkillResult objects
"""

from kyrax_core.skill_registry import SkillRegistry
from kyrax_core.dispatcher import Dispatcher
from kyrax_core.intent_mapper import map_nlu_to_command

# Skills (example implementations included previously)
from skills.whatsapp_skill import WhatsAppSkill
from skills.os_skill import OSSkill
from skills.iot_skill import IoTSkill


def demo():
    registry = SkillRegistry()
    # register skills in order of priority
    registry.register(WhatsAppSkill())
    registry.register(OSSkill(dry_run=True))   # safe default
    registry.register(IoTSkill(mqtt_client=None))

    dispatcher = Dispatcher(registry=registry, min_confidence=0.0)

    # 1) WhatsApp send_message
    nlu1 = {"intent": "send_message", "slots": {"contact": "Rohit", "message": "Hello buddy", "app": "whatsapp"}, "confidence": 0.95}
    cmd1 = map_nlu_to_command(nlu1, source="voice")
    res1 = dispatcher.execute(cmd1)
    print("CMD1:", cmd1)
    print("RES1:", res1)

    # 2) OS open app (safe dry run)
    nlu2 = {"intent": "open_app", "slots": {"app": "code"}, "confidence": 0.90}
    cmd2 = map_nlu_to_command(nlu2, source="voice")
    res2 = dispatcher.execute(cmd2)
    print("CMD2:", cmd2)
    print("RES2:", res2)

    # 3) IoT: turn on light (simulated)
    nlu3 = {"intent": "turn_on", "slots": {"device": "bedroom_light"}, "confidence": 0.99}
    cmd3 = map_nlu_to_command(nlu3, source="voice")
    res3 = dispatcher.execute(cmd3)
    print("CMD3:", cmd3)
    print("RES3:", res3)


if __name__ == "__main__":
    demo()