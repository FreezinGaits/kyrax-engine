from typing import Optional
from kyrax_core.command import Command

_pending: Optional[Command] = None

def set_pending(cmd: Command):
    global _pending
    _pending = cmd

def get_pending() -> Optional[Command]:
    return _pending

def clear_pending():
    global _pending
    _pending = None