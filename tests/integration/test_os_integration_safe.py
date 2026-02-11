import os
import pytest
from kyrax_core.command import Command
from kyrax_core.guards import GuardManager
from skills.os_skill import OSSkill

@pytest.mark.integration
def test_os_shutdown_is_blocked_in_dry_run():
    os.environ["KYRAX_FORCE_DRY_RUN"] = "1"

    cmd = Command(intent="shutdown", domain="os", entities={}, confidence=1.0, source="test")
    gm = GuardManager()
    res = gm.validate(cmd, user={"id": "u1", "roles": ["admin"]})

    assert res.blocked is True
    assert res.reason == "dry_run_blocked"
