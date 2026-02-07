# tests/test_os_backends_and_skill.py
import platform
import types
import pytest
from skills.os_backends import WindowsBackend, LinuxBackend, MacBackend, get_backend_for_current_platform
from skills.os_skill import OSSkill
from kyrax_core.command import Command

def test_linux_backend_dry_run():
    b = LinuxBackend()
    r = b.set_volume(30, dry_run=True)
    assert r["ok"] and r["dry_run"]

def test_mac_backend_dry_run():
    b = MacBackend()
    r = b.mute(True, dry_run=True)
    assert r["ok"] and r["dry_run"]

def test_windows_backend_mock_pycaw(monkeypatch):
    # Simulate pycaw present by setting attributes used by WindowsBackend
    import types
    fake_AudioUtilities = types.SimpleNamespace(GetSpeakers=lambda: types.SimpleNamespace(Activate=lambda iid, ctx, x: "iface"))
    # fake IAudioEndpointVolume class with methods used
    class FakeVol:
        def SetMasterVolumeLevelScalar(self, v, _): self._v = v
        def GetMasterVolumeLevelScalar(self): return getattr(self, "_v", 0.5)
        def SetMute(self, m, _): self._m = m
    def fake_cast(interface, pointer):
        return FakeVol()
    # monkeypatch imports inside module
    wb = WindowsBackend()
    # inject attributes directly (bypass __init__ checks)
    wb.available = True
    wb._AudioUtilities = fake_AudioUtilities
    wb._IAudioEndpointVolume = types.SimpleNamespace(_iid_="iid")
    wb._CLSCTX_ALL = None
    wb._cast = fake_cast
    wb._POINTER = lambda x: x
    r = wb.set_volume(42, dry_run=True)
    assert r["ok"] and r["dry_run"]
    r2 = wb.set_volume(42, dry_run=False)
    assert r2["ok"] and r2.get("level", 42) in (42, int(round(42)))
    # mute
    rm = wb.mute(True, dry_run=False)
    assert rm["ok"]

def test_osskill_dispatch_dry_run():
    s = OSSkill(dry_run=True)
    cmd = Command(intent="set_volume", domain="os", entities={"level": 10})
    r = s.execute(cmd)
    assert r.success is True
