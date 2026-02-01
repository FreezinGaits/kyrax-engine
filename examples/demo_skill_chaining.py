# examples/demo_skill_chaining.py
from kyrax_core.command import Command
from kyrax_core.chain_executor import ChainExecutor
from typing import Dict, Any

# Dummy dispatcher implementing three "skills":
#  - download_file -> returns {"file_path": "/tmp/xyz.txt"}
#  - attach_file   -> returns {"attachment_id": "att-123", "file_path": ...}
#  - send_email    -> returns {"sent": True, "to": "Rohit"}
class DummyDispatcher:
    def dispatch(self, cmd: Command) -> Dict[str, Any]:
        print(f"[DISPATCH] intent={cmd.intent}, domain={cmd.domain}, entities={cmd.entities}")
        if cmd.intent == "download_file":
            # pretend we downloaded and saved
            path = "/tmp/downloaded_report.pdf"
            return {"file_path": path, "size": 12345}
        if cmd.intent == "attach_file":
            file_path = cmd.entities.get("file_path") or cmd.entities.get("path")
            return {"attachment_id": "att-001", "file_path": file_path}
        if cmd.intent == "send_email":
            to = cmd.entities.get("to") or cmd.entities.get("contact")
            subject = cmd.entities.get("subject")
            return {"sent": True, "to": to, "subject": subject}
        # fallback
        return {"ok": True, "intent": cmd.intent}

def demo():
    # plan: download -> attach -> send
    cmds = [
        Command(intent="download_file", domain="file", entities={"url": "https://example.com/report.pdf"}),
        # use placeholder to refer to last step's file_path
        Command(intent="attach_file", domain="application", entities={"file_path": "{{ last.file_path }}"}),
        # send email using the attachment - can reference steps.1.attachment_id or last.attachment_id
        Command(intent="send_email", domain="application", entities={"to": "Rohit", "subject": "Report", "attachment": "{{ last.attachment_id }}"})
    ]

    dispatcher = DummyDispatcher()
    chain = ChainExecutor()
    results, issues = chain.execute_chain(cmds, dispatcher)
    print("\n=== RESULTS ===")
    for i, r in enumerate(results):
        print(i, r)
    print("\n=== ISSUES ===")
    for it in issues:
        print(it)

if __name__ == "__main__":
    demo()
