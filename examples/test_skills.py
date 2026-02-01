# examples/test_skills.py
from kyrax_core.skill_registry import SkillRegistry
from skills.whatsapp_skill import WhatsAppSkill
from skills.os_skill import OSSkill
from skills.iot_skill import IoTSkill
from kyrax_core.intent_mapper import map_nlu_to_command

def main():
    registry = SkillRegistry()
    registry.register(WhatsAppSkill())
    registry.register(OSSkill(dry_run=True))   # safe by default
    registry.register(IoTSkill(mqtt_client=None))

    # Example 1: send whatsapp message
    nlu1 = {"intent": "send_message", "slots": {"contact": "Rohit", "message": "Hi", "app": "whatsapp"}, "confidence": 0.95}
    cmd1 = map_nlu_to_command(nlu1, source="voice")
    handler = registry.find_handler(cmd1)
    print("Handler for cmd1:", handler.name if handler else "NONE")
    res1 = handler.execute(cmd1) if handler else None
    print("Result1:", res1)

    # Example 2: open VSCode (OS skill)
    nlu2 = {"intent": "open_app", "slots": {"app": "code"}, "confidence": 0.92}
    cmd2 = map_nlu_to_command(nlu2, source="voice")
    handler2 = registry.find_handler(cmd2)
    print("Handler for cmd2:", handler2.name if handler2 else "NONE")
    res2 = handler2.execute(cmd2) if handler2 else None
    print("Result2:", res2)

    # Example 3: turn on lamp (IoT)
    nlu3 = {"intent": "turn_on", "slots": {"device": "bedroom_light"}, "confidence": 0.98}
    cmd3 = map_nlu_to_command(nlu3, source="voice")
    handler3 = registry.find_handler(cmd3)
    print("Handler for cmd3:", handler3.name if handler3 else "NONE")
    res3 = handler3.execute(cmd3) if handler3 else None
    print("Result3:", res3)


if __name__ == "__main__":
    main()
