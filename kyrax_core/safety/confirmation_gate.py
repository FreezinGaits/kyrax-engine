from kyrax_core.command import Command

CONFIRM_REQUIRED = {
    "shutdown",
    "restart",
    "sleep",
    "open_app",
    "close_app",
}

def requires_confirmation(command: Command) -> bool:
    return command.domain == "os" and command.intent in CONFIRM_REQUIRED