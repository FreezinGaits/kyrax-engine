# tests/test_guards_os.py
import pytest
from kyrax_core.command import Command
from kyrax_core.guards import GuardManager
from kyrax_core.dispatcher import Dispatcher
from kyrax_core.skill_registry import SkillRegistry

# Use os_policy directly to control dry-run in tests
import kyrax_core.os_policy as os_policy

def test_guard_blocks_high_risk_in_dry_run(monkeypatch):
    monkeypatch.setattr(os_policy, "dry_run_enabled", lambda: True)
    g = GuardManager()

    cmd = Command(intent="shutdown", domain="os", entities={})

    # non-admin → blocked
    res_user = g.validate(cmd, {"id": "u1", "roles": ["user"]})
    assert res_user.blocked is True

    # admin → confirmation required (NOT blocked)
    res_admin = g.validate(cmd, {"id": "admin", "roles": ["admin"]})
    assert res_admin.blocked is False
    assert res_admin.require_confirmation is True
    assert "dry_run" in (res_admin.reason or "")


def test_guard_requires_confirmation_for_high_risk_when_admin(monkeypatch):
    # dry_run disabled so confirmation path activates
    monkeypatch.setattr(os_policy, "dry_run_enabled", lambda: False)
    g = GuardManager()

    cmd = Command(intent="shutdown", domain="os", entities={})
    # admin user should reach require_confirmation=True
    res = g.validate(cmd, {"id": "u1", "roles": ["admin"]})
    assert res.blocked is False
    assert res.require_confirmation is True

def test_dispatcher_confirmation_flow(monkeypatch):
    # ensure dry_run disabled
    monkeypatch.setattr(os_policy, "dry_run_enabled", lambda: False)
    g = GuardManager()
    registry = SkillRegistry()
    # create dispatcher with guard_manager but no default_confirm_fn
    dispatcher = Dispatcher(registry=registry, guard_manager=g, default_user={"id":"local","roles":["admin"]})

    cmd = Command(intent="shutdown", domain="os", entities={})
    # No confirm_fn provided -> execute returns SkillResult with a message indicating confirmation required
    res = dispatcher.execute(cmd)
    assert res.success is False
    assert "Confirmation required" in res.message or "confirm" in res.message.lower()

    # Now provide a confirm_fn that returns True: dispatcher should proceed to handler lookup and fail (no skill registered)
    def yes(prompt: str) -> bool:
        return True

    res2 = dispatcher.execute(cmd, confirm_fn=yes)
    assert res2.success is False
    # Because no skill is registered, we should get "No skill registered..."
    assert "No skill registered" in res2.message
