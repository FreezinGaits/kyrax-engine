from kyrax_core.command import Command
from kyrax_core.guards import GuardManager
from skills.os_skill import OSSkill

cmd = Command(
    intent="set_volume",
    domain="os",
    entities={"level": 60},
    confidence=1.0,
    source="pipeline_test"
)

gm = GuardManager()

res = gm.guard_and_dispatch(
    cmd,
    user={"id": "local_user", "roles": ["user"]},
    dispatcher_callable=lambda c: OSSkill().execute(c)
)

print(res)