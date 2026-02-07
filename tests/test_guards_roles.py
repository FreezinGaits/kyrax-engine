# tests/test_guards_roles.py
import types
from kyrax_core.guards import GuardManager
from kyrax_core.command import Command
from kyrax_core.os_policy import HIGH_RISK_INTENTS

def fake_dispatcher(cmd):
    return {"ok": True, "cmd": getattr(cmd, "intent", None)}

def test_high_risk_requires_admin_by_default():
    gm = GuardManager(skill_registry_checker=lambda c: True)
    # pick a high risk intent (if available), else use 'shutdown'
    intent = (HIGH_RISK_INTENTS[0] if HIGH_RISK_INTENTS else "shutdown")
    cmd = Command(intent=intent, domain="os", entities={})
    # non-admin user
    user = {"id": "u1", "roles": ["user"]}
    res = gm.guard_and_dispatch(cmd, user, dispatcher_callable=fake_dispatcher, confirm_fn=lambda p: True)
    assert res["status"] in ("blocked", "cancelled", "error")
    # admin user should be allowed (but ask confirm -> our confirm_fn returns True)
    admin_user = {"id": "admin", "roles": ["admin"]}
    res2 = gm.guard_and_dispatch(cmd, admin_user, dispatcher_callable=fake_dispatcher, confirm_fn=lambda p: True)
    assert res2["status"] == "executed"
    assert res2["result"]["ok"] is True

def test_non_high_risk_allowed_for_user():
    gm = GuardManager(skill_registry_checker=lambda c: True)
    cmd = Command(intent="set_volume", domain="os", entities={"level": 10})
    user = {"id": "u1", "roles": ["user"]}
    res = gm.guard_and_dispatch(cmd, user, dispatcher_callable=fake_dispatcher, confirm_fn=lambda p: True)
    assert res["status"] == "executed"
