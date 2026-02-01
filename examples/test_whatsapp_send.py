# examples/test_whatsapp_send.py
"""
Example showing the WhatsAppSkill in action.
Run from project root:
    python -m examples.test_whatsapp_send
"""

# import time
# from kyrax_core.command import Command
# from skills.whatsapp_skill import WhatsAppSkill

# def main():
#     # set profile_dir to persist your WhatsApp Web login (recommended).
#     # Ensure that directory exists or Chrome will create it.
#     profile_dir = r"C:\Users\HP\kyrax_chrome_profile"  # change to your platform path
#     # If you want to use a local chromedriver instead of auto-download, set driver_path.
#     skill = WhatsAppSkill(
#         profile_dir=profile_dir,
#         headless=False,
#         driver_path=None,         # None -> use webdriver-manager (auto)
#         close_on_finish=False,    # keep session for reuse
#         use_webdriver_manager=True
#     )

#     cmd = Command(
#         intent="send_message",
#         domain="application",
#         entities={"contact": "Rohit", "text": "I'll be late"},
#         confidence=0.98,
#         source="voice"
#     )

#     print("Sending message...")
#     res = skill.execute(cmd)
#     print("Result:", res)

#     # Keep browser open for debugging; if you want to close it:
#     if skill.driver:
#         print("Driver open. Sleeping 3s then closing (remove in production if you keep persistent session).")
#         time.sleep(3)
#         skill.driver.quit()

# if __name__ == "__main__":
#     main()













# examples/test_whatsapp_send.py
"""
Example using Playwright-backed WhatsAppSkill.
Run:
  python -m examples.test_whatsapp_send
Make sure you installed Playwright browsers already:
  pip install playwright
  playwright install
"""

import time
from kyrax_core.command import Command
from skills.whatsapp_skill import WhatsAppSkill

def main():
    # persistent profile recommended for QR-auth persistence
    profile_dir = r"C:\Users\HP\kyrax_wa_profile"  # change to your platform path
    skill = WhatsAppSkill(
        profile_dir=profile_dir,
        headless=False,          # must be False if you need to scan QR
        close_on_finish=False,   # keep logged-in session
        browser_type="chromium"  # or "firefox"/"webkit"
    )

    cmd = Command(
        intent="send_message",
        domain="application",
        entities={"contact": "Akshat Pawar", "text": "aiiiiiiiiii"},
        confidence=0.98,
        source="voice"
    )

    print("Sending message...")
    res = skill.execute(cmd)
    print("Result:", res)

    # If you want to close browser after a short while (for debugging)
    # if skill._page and not skill.close_on_finish:
    #     print("Sleeping 3s then closing for demo (remove in production to keep session).")
    #     time.sleep(3)
    #     skill._cleanup()

if __name__ == "__main__":
    main()
