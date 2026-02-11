from kyrax_core.command import Command
from skills.os_skill import OSSkill

cmd = Command(
    intent="set_volume",
    domain="os",
    entities={"level": 30},
    confidence=1.0,
    source="manual_test"
)

skill = OSSkill()
result = skill.execute(cmd)

print(result)
