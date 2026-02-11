# kyrax_core/contact_store.py
import json
from pathlib import Path

class ContactStore:
    def __init__(self, path="data/contacts.json"):
        self.path = Path(path)
        self.path.parent.mkdir(exist_ok=True)

    def load(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def save(self, contacts: dict):
        self.path.write_text(json.dumps(contacts, indent=2))
