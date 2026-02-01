# examples/demo_guardrails.py
from kyrax_core.command import Command
from kyrax_core.guards import GuardManager
from kyrax_core.audit import audit_record

# stub dispatcher
def fake_dispatcher(cmd: Command):
    # pretend we executed
    return {"ok": True, "msg": f"executed {cmd.intent}"}

# stub confirm function (in real UI, ask the human)
def cli_confirm(prompt: str) -> bool:
    print("[CONFIRM]", prompt)
    ans = input("Type 'yes' to confirm: ").strip().lower()
    return ans == "yes"

def demo():
    gm = GuardManager()

    user_admin = {"id": "u1", "roles": ["admin", "user"], "name": "Admin"}
    user_basic = {"id": "u2", "roles": ["user"], "name": "Basic"}

    # destructive command example
    cmd1 = Command(intent="delete_file", domain="file", entities={"path": "/"}, confidence=0.95, source="voice")
    out = gm.guard_and_dispatch(cmd1, user_admin, fake_dispatcher, confirm_fn=cli_confirm)
    audit_record({"user": user_admin["id"], "cmd": cmd1.to_json(), "guard_out": out})
    print("Result admin:", out)

    # basic command allowed
    cmd2 = Command(intent="open_app", domain="os", entities={"app": "vscode"}, confidence=0.9, source="text")
    out2 = gm.guard_and_dispatch(cmd2, user_basic, fake_dispatcher, confirm_fn=cli_confirm)
    audit_record({"user": user_basic["id"], "cmd": cmd2.to_json(), "guard_out": out2})
    print("Result basic:", out2)

if __name__ == "__main__":
    demo()
