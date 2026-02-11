# tests/test_command_builder_os.py
import pytest
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.command import Command

def test_set_volume_valid_integer():
    b = CommandBuilder()
    nlu = {"intent": "set_volume", "entities": {"level": "50"}, "confidence": 0.9}
    cmd, issues = b.build(nlu, source="test")
    assert cmd is not None, f"Expected command, got issues: {issues}"
    assert cmd.intent == "set_volume"
    assert isinstance(cmd.entities.get("level"), int)
    assert cmd.entities["level"] == 50
    assert issues == []  # no issues for clean input

def test_set_volume_valid_percent_string():
    b = CommandBuilder()
    nlu = {"intent": "set_volume", "entities": {"level": "72%"}, "confidence": 0.9}
    cmd, issues = b.build(nlu, source="test")
    assert cmd is not None
    assert cmd.entities["level"] == 72
    assert issues == []
    

def test_set_volume_invalid_parse_fails():
    b = CommandBuilder()
    nlu = {"intent": "set_volume", "entities": {"level": "loud"}, "confidence": 0.9}
    cmd, issues = b.build(nlu, source="test")
    # normalization failure on required field should lead to no command and a missing_required_entity
    assert cmd is None
    assert any(i.startswith("missing_required_entity:level") for i in issues), f"issues: {issues}"

def test_shutdown_no_entities_allowed():
    b = CommandBuilder()
    nlu = {"intent": "shutdown", "entities": {}, "confidence": 0.8}
    cmd, issues = b.build(nlu, source="test")
    # Shutdown has no required entities in schema, so builder returns a Command
    assert cmd is not None
    assert cmd.intent == "shutdown"
    assert issues == [] or all(not i.startswith("missing_required_entity") for i in issues)
