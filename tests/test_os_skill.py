# File: tests/test_os_skill.py
import pytest
from types import SimpleNamespace
from kyrax_core.command import Command
from skills.os_skill import OSSkill
import skills.os_skill as os_skill_module
import subprocess

# Helper fake runner to capture last command run
class FakeProc:
    def __init__(self, ok=True, stdout="", stderr="", returncode=0):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

def test_set_volume_dry_run():
    s = OSSkill(dry_run=True)
    cmd = Command(intent="set_volume", domain="os", entities={"level": 30})
    res = s.execute(cmd)
    assert res.success is True
    assert "dry-run" in (res.message or "").lower() or res.data.get("cmd")

def test_shutdown_dry_run():
    s = OSSkill(dry_run=True)
    cmd = Command(intent="shutdown", domain="os", entities={})
    res = s.execute(cmd)
    assert res.success is True
    assert "dry-run" in (res.message or "").lower() or res.data.get("cmd")

def test_close_app_uses_taskkill_on_windows(monkeypatch):
    # Simulate windows platform and subprocess.run capturing
    monkeypatch.setattr(os_skill_module, "platform", SimpleNamespace(system=lambda: "Windows"))
    captured = {}
    def fake_run(args, check=True, capture_output=True, text=True):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(os_skill_module, "subprocess", SimpleNamespace(run=fake_run))
    s = OSSkill(dry_run=True)
    cmd = Command(intent="close_app", domain="os", entities={"app": "notepad.exe"})
    res = s.execute(cmd)
    assert res.success is True
    assert "taskkill" in " ".join(captured["args"]).lower()

def test_set_volume_linux_uses_amixer(monkeypatch):
    monkeypatch.setattr(os_skill_module, "platform", SimpleNamespace(system=lambda: "Linux"))
    # pretend amixer exists
    monkeypatch.setattr(os_skill_module, "shutil", SimpleNamespace(which=lambda x: "/usr/bin/amixer"))
    called = {}
    def fake_run(args, check=True, capture_output=True, text=True):
        called["args"] = args
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(os_skill_module, "subprocess", SimpleNamespace(run=fake_run))
    s = OSSkill(dry_run=True)
    cmd = Command(intent="set_volume", domain="os", entities={"level": 55})
    res = s.execute(cmd)
    assert res.success is True
    assert "amixer" in called["args"][0]

def test_power_action_all_candidates_fail(monkeypatch):
    # Simulate linux but subprocess.run will fail
    monkeypatch.setattr(os_skill_module, "platform", SimpleNamespace(system=lambda: "Linux"))
    def fake_run(args, check=True, capture_output=True, text=True):
        raise subprocess.CalledProcessError(returncode=1, cmd=args, output="", stderr="denied")
    monkeypatch.setattr(os_skill_module, "subprocess", SimpleNamespace(run=fake_run))
    s = OSSkill(dry_run=True)
    cmd = Command(intent="shutdown", domain="os", entities={})
    res = s.execute(cmd)
    assert res.success is False
    assert "failed" in (res.message or "").lower()
