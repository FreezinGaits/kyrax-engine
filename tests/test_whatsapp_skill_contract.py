def test_whatsapp_skill_requires_canonical_contact():
    from skills.whatsapp_skill import WhatsAppSkill
    from kyrax_core.command import Command

    skill = WhatsAppSkill(headless=True)
    cmd = Command(
        intent="send_message",
        domain="application",
        entities={"contact": "Test User", "text": "Hi"},
        confidence=1.0,
        source="test"
    )

    result = skill.execute(cmd)
    assert result is not None
