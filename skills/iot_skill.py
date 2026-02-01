# skills/iot_skill.py
from typing import Optional, Dict, Any
from kyrax_core.skill_base import Skill, SkillResult
from kyrax_core.command import Command


class IoTSkill(Skill):
    name = "iot"

    def __init__(self, mqtt_client=None):
        """
        mqtt_client: optional pre-configured client (paho-mqtt or similar).
                     If None, the skill will simulate IoT actions.
        """
        self.client = mqtt_client

    def can_handle(self, command: Command) -> bool:
        return command.domain == "iot" and command.intent.lower() in ("turn_on", "turn_off", "set", "toggle")

    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        device = command.entities.get("device")
        action = command.intent.lower()
        value = command.entities.get("value")

        if not device:
            return SkillResult(False, "No device specified", {"missing": "device"})

        payload = {"action": action, "device": device}
        if value is not None:
            payload["value"] = value

        if self.client:
            # Example: publish to topic 'kyrax/iot/<device>'
            topic = f"kyrax/iot/{device}"
            # client must implement publish(topic, payload) — adapt as needed
            try:
                # Convert payload to string/json depending on client
                self.client.publish(topic, str(payload))
                return SkillResult(True, f"Command sent to device '{device}'", {"topic": topic, "payload": payload})
            except Exception as ex:
                return SkillResult(False, f"MQTT publish failed: {ex}")
        else:
            # Simulation mode
            return SkillResult(True, f"Simulated IoT {action} for {device}", {"simulated_payload": payload})
