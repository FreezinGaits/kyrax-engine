# examples/demo_workflow_manager.py
"""
Simple demo showing creation of a workflow, executing step-by-step with updates to WorkflowStore.
"""

from kyrax_core.command import Command
from kyrax_core.workflow_manager import WorkflowStore, STATUS_COMPLETED, STATUS_FAILED
import time

class DummyDispatcher:
    def dispatch(self, cmd: Command):
        print(f"[DISPATCH] {cmd.intent} => {cmd.entities}")
        # simulate behaviour
        if cmd.intent == "download_file":
            return {"file_path": "/tmp/report.pdf", "size": 12_345}
        if cmd.intent == "attach_file":
            # expect file_path entity
            return {"attachment_id": "att-100", "file_path": cmd.entities.get("file_path")}
        if cmd.intent == "send_email":
            return {"sent": True, "to": cmd.entities.get("to")}
        # unknown
        return {"ok": True}

def run_workflow_demo():
    store = WorkflowStore(path=":memory:")  # use file path to persist
    dispatcher = DummyDispatcher()

    # build commands (the planner would normally produce these)
    cmds = [
        Command(intent="download_file", domain="file", entities={"url": "https://example.com/report.pdf"}),
        Command(intent="attach_file", domain="application", entities={"file_path": "{{ last.file_path }}"}),  # templated; assume your chain executor resolves this
        Command(intent="send_email", domain="application", entities={"to": "Rohit", "subject": "Report", "attachment": "{{ last.attachment_id }}"})
    ]

    wf_id = store.create_workflow(goal="Send report to Rohit", commands=cmds)
    print("created workflow:", wf_id)

    # naive executor loop: get next pending step, execute, update store
    while True:
        step = store.get_next_pending_step(wf_id)
        if not step:
            print("no more pending steps")
            break

        print("executing step:", step.step_id, step.command.intent)
        store.mark_step_in_progress(wf_id, step.step_id)

        # IMPORTANT in your real code: resolve placeholders ({{ last.xxx }}) with outputs from previous steps.
        # For demo simplicity we will do manual resolution here.
        # load previous completed step result for basic substitution
        steps_all = store.get_all_steps(wf_id)
        last_result = None
        for s in steps_all:
            if s.status == STATUS_COMPLETED:
                last_result = s.result

        # simple manual resolve for demo
        cmd = Command.from_json(step.command.to_json())
        if isinstance(cmd.entities.get("file_path"), str) and "{{ last.file_path }}" in cmd.entities.get("file_path"):
            if last_result and last_result.get("file_path"):
                cmd.entities["file_path"] = last_result["file_path"]

        try:
            res = dispatcher.dispatch(cmd)
            store.mark_step_completed(wf_id, step.step_id, result=res)
        except Exception as e:
            store.mark_step_failed(wf_id, step.step_id, error=str(e))
            # policy: stop on failure for demo
            break

    print("final workflow state:")
    print(store.explain_workflow(wf_id))

if __name__ == "__main__":
    run_workflow_demo()
