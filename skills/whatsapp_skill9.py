# skills/whatsapp_skill.py
# from kyrax_core.skill_base import Skill, SkillResult
# from kyrax_core.command import Command


# class WhatsAppSkill(Skill):
#     name = "whatsapp"

#     def can_handle(self, command: Command) -> bool:
#         # handle only application-level send_message to whatsapp
#         if command.domain != "application":
#             return False
#         if command.intent.lower() not in ("send_message", "send_media", "send"):
#             return False
#         app = command.entities.get("app", "").lower()
#         return app in ("whatsapp", "wa", "whatsapp_web")

#     def execute(self, command: Command, context=None) -> SkillResult:
#         contact = command.entities.get("contact")
#         text = command.entities.get("text")
#         media = command.entities.get("media")

#         if not contact:
#             return SkillResult(False, "Missing contact to send message to", {"missing": "contact"})

#         # In this example we **simulate** sending. In real implementation call WhatsApp API/automation.
#         payload = {
#             "to": contact,
#             "text": text,
#             "media": media
#         }

#         # Replace this block with real API call or browser automation.
#         simulated = {
#             "status": "sent",
#             "payload": payload
#         }

#         return SkillResult(True, f"Message queued for {contact}", data=simulated)






















 # skills/whatsapp_skill.py
# """
# WhatsApp skill (Selenium) for KYRAX / Kyrax project.
# - Keeps driver open by default to reuse QR-authenticated session.
# - Optionally uses webdriver-manager to auto-download a matching chromedriver.
# - Resolves contacts from data/contacts.json (simple registry).
# """

# import time
# import json
# import re
# from typing import Dict, Any, Optional

# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.common.exceptions import TimeoutException, WebDriverException
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC

# from webdriver_manager.chrome import ChromeDriverManager

# # Import the skill contract from your kyrax_core package
# try:
#     from kyrax_core.command import Command
#     from kyrax_core.skill_base import Skill, SkillResult
# except Exception:
#     # Fallbacks if running examples standalone (lightweight)
#     from dataclasses import dataclass

#     @dataclass
#     class Command:
#         intent: str
#         domain: str
#         entities: dict
#         confidence: float = 1.0
#         source: str = "voice"

#     @dataclass
#     class SkillResult:
#         success: bool
#         message: str
#         data: Optional[Dict[str, Any]] = None

#     class Skill:
#         name = "whatsapp"
#         def can_handle(self, command): return False
#         def execute(self, command, context=None): return SkillResult(False, "Not implemented")


# class WhatsAppSkill(Skill):
#     name = "whatsapp"

#     def __init__(
#         self,
#         profile_dir: Optional[str] = None,
#         headless: bool = False,
#         driver_path: Optional[str] = None,
#         contacts_path: str = "data/contacts.json",
#         close_on_finish: bool = False,
#         use_webdriver_manager: bool = True,
#     ):
#         """
#         profile_dir: chrome user-data dir to persist WhatsApp Web login (QR scan).
#         headless: whether to run headless (QR scanning not possible in headless).
#         driver_path: explicit chromedriver path (optional).
#         close_on_finish: if True, quit driver after each execute() call.
#         use_webdriver_manager: if True and driver_path is None, auto-download matching chromedriver.
#         """
#         self.profile_dir = profile_dir
#         self.headless = headless
#         self.driver_path = driver_path
#         self.close_on_finish = close_on_finish
#         self.use_webdriver_manager = use_webdriver_manager

#         # load contacts registry (optional)
#         self.contacts = {}
#         try:
#             with open(contacts_path, "r", encoding="utf-8") as f:
#                 self.contacts = json.load(f)
#         except FileNotFoundError:
#             # leave empty and allow raw names/phones
#             self.contacts = {}
#         except Exception:
#             self.contacts = {}

#         self.driver = None

#     def can_handle(self, command: Command) -> bool:
#         if not hasattr(command, "intent"):
#             return False
#         return (
#             command.domain == "application"
#             and command.intent == "send_message"
#             and ("text" in (command.entities or {}) or "message" in (command.entities or {}))
#         )

#     def _ensure_driver(self):
#         if self.driver:
#             return

#         chrome_options = Options()
#         if self.profile_dir:
#             chrome_options.add_argument(f"--user-data-dir={self.profile_dir}")
#         if self.headless:
#             # headless prevents QR scanning; use only for automated servers with pre-authenticated session
#             chrome_options.add_argument("--headless=new")
#             chrome_options.add_argument("--disable-gpu")
#         chrome_options.add_argument("--no-sandbox")
#         chrome_options.add_argument("--disable-dev-shm-usage")
#         chrome_options.add_argument("--disable-extensions")
#         # avoid detection flags
#         chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
#         chrome_options.add_experimental_option("useAutomationExtension", False)

#         try:
#             if self.driver_path:
#                 service = Service(self.driver_path)
#             else:
#                 if self.use_webdriver_manager:
#                     driver_bin = ChromeDriverManager().install()
#                     service = Service(driver_bin)
#                 else:
#                     service = None

#             if service is not None:
#                 self.driver = webdriver.Chrome(service=service, options=chrome_options)
#             else:
#                 self.driver = webdriver.Chrome(options=chrome_options)

#             self.driver.set_page_load_timeout(30)
#             try:
#                 self.driver.get("https://web.whatsapp.com")
#             except Exception:
#                 # ignore occasional timeout; page might still be usable
#                 pass

#         except WebDriverException as e:
#             raise RuntimeError(f"Failed to start ChromeDriver: {e}")

#     def _find_and_open_chat(self, contact_query: str, timeout: int = 20) -> bool:
#         """
#         Search and open chat for contact_query (name or phone). Returns True if chat opened.
#         """
#         self._ensure_driver()
#         wait = WebDriverWait(self.driver, timeout)

#         # A few different selectors as WhatsApp Web UI varies
#         search_selectors = [
#             "//div[@contenteditable='true' and @data-testid='chat-list-search']",
#             "//div[@contenteditable='true'][@aria-label='Search input textbox']",
#             "//div[@contenteditable='true'][@title='Search or start new chat']",
#             "//div[@role='textbox'][@title='Search input textbox']",
#             "//div[contains(@class,'_2_1wd copyable-text selectable-text')]"
#         ]

#         search_input = None
#         for sel in search_selectors:
#             try:
#                 search_input = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
#                 break
#             except TimeoutException:
#                 continue

#         if not search_input:
#             # last-resort: try to open search by pressing CTRL+F (less reliable)
#             try:
#                 return False
#             except Exception:
#                 return False

#         try:
#             search_input.click()
#             # clear existing content (if any)
#             try:
#                 search_input.clear()
#             except Exception:
#                 pass
#             search_input.send_keys(contact_query)
#             # small sleep to let results populate
#             time.sleep(1.0)

#             # try to click exact match
#             try:
#                 el = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[@title=\"{contact_query}\"]")))
#                 el.click()
#                 return True
#             except TimeoutException:
#                 # fallback: press Enter to open first result
#                 try:
#                     search_input.send_keys("\n")
#                     time.sleep(0.8)
#                     return True
#                 except Exception:
#                     return False
#         except Exception:
#             return False

#     def _send_text(self, message: str, timeout: int = 10) -> bool:
#         wait = WebDriverWait(self.driver, timeout)
#         msg_selectors = [
#             "//div[@contenteditable='true' and @data-testid='conversation-compose-box-input']",
#             "//div[@aria-label='Type a message']",
#             "//footer//div[@contenteditable='true']",
#             "//div[contains(@class,'_3uMse')]//div[@contenteditable='true']"
#         ]
#         msg_box = None
#         for sel in msg_selectors:
#             try:
#                 msg_box = wait.until(EC.presence_of_element_located((By.XPATH, sel)))
#                 break
#             except TimeoutException:
#                 continue
#         if not msg_box:
#             return False

#         try:
#             msg_box.click()
#             # ensure focus
#             time.sleep(0.05)
#             msg_box.send_keys(message)
#             msg_box.send_keys("\n")
#             time.sleep(0.5)
#             return True
#         except Exception:
#             return False

#     def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
#         """
#         Execute send_message command. Returns SkillResult(success, message, data).
#         """
#         contact = (command.entities or {}).get("contact") or (command.entities or {}).get("to")
#         # normalize message keys
#         text = (command.entities or {}).get("text") or (command.entities or {}).get("message")

#         if not text:
#             return SkillResult(False, "No text provided")

#         if not contact:
#             return SkillResult(False, "No contact provided")

#         # Resolve contact: check contacts registry, or use phone if numeric
#         cinfo = self.contacts.get(contact) or next(
#             (v for k, v in self.contacts.items() if k.lower() == str(contact).lower()), None
#         )
#         contact_query = None
#         if cinfo:
#             contact_query = cinfo.get("whatsapp_name") or cinfo.get("name") or cinfo.get("phone") or contact
#         else:
#             # if looks like phone number:
#             s = str(contact).strip()
#             if re.sub(r'\D', '', s).isdigit() and len(re.sub(r'\D', '', s)) >= 7:
#                 contact_query = s
#             else:
#                 contact_query = contact

#         try:
#             opened = self._find_and_open_chat(contact_query)
#             if not opened:
#                 return SkillResult(False, f"Contact '{contact_query}' not found", {"contact_query": contact_query})

#             sent = self._send_text(text)
#             if not sent:
#                 return SkillResult(False, "Failed to send message")

#             return SkillResult(True, f"Message sent to {contact_query}", {"text": text, "contact_query": contact_query})
#         except Exception as e:
#             return SkillResult(False, f"Exception during send: {e}")
#         finally:
#             # only quit driver if user wanted ephemeral sessions
#             if self.driver and self.close_on_finish:
#                 try:
#                     self.driver.quit()
#                 except Exception:
#                     pass
#                 self.driver = None

















# skills/whatsapp_skill.py
"""
WhatsApp skill implemented with Playwright (sync API).
Requires: pip install playwright
And browsers installed: playwright install

Notes:
- For persistent WhatsApp Web session, provide profile_dir (persistent user_data directory).
- headless=False required for QR scanning on first run.
- Works with Chromium by default; change to firefox/webkit if desired.
"""

# skills/whatsapp_skill.py
import time
import json
import re
import os
from typing import Dict, Any, Optional
import shutil, platform, subprocess

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

class PlaywrightManager:
    _pw = None

    @classmethod
    def get(cls):
        if cls._pw is None:
            cls._pw = sync_playwright().start()
        return cls._pw

# Skill contract import
try:
    from kyrax_core.command import Command
    from kyrax_core.skill_base import Skill, SkillResult
except Exception:
    from dataclasses import dataclass
    @dataclass
    class Command:
        intent: str
        domain: str
        entities: dict
        confidence: float = 1.0
        source: str = "voice"
    @dataclass
    class SkillResult:
        success: bool
        message: str
        data: Optional[Dict[str, Any]] = None
    class Skill:
        name = "whatsapp"
        def can_handle(self, command): return False
        def execute(self, command, context=None): return SkillResult(False, "Not implemented")

class WhatsAppSkill(Skill):
    name = "whatsapp"

    def __init__(self, profile_dir: Optional[str] = None, headless: bool = False, close_on_finish: bool = False, browser_type: str = "chromium"):
        self.profile_dir = profile_dir
        self.headless = headless
        self.close_on_finish = close_on_finish
        self.browser_type = browser_type
        self.contacts = {}
        try:
            with open("data/contacts.json", "r", encoding="utf-8") as f:
                self.contacts = json.load(f)
        except Exception:
            self.contacts = {}
        self._pw = None
        self._context = None
        self._page = None
    
    # ---------- page/context health helpers ----------
    def _is_context_alive(self) -> bool:
        if not self._context:
            return False
        try:
            # simple check accessing pages; will raise if closed
            _ = self._context.pages
            return True
        except Exception:
            return False

    def _ensure_browser(self):
        # If context dead, recreate it
        if not self._is_context_alive():
            # start playwright if needed
            pw = PlaywrightManager.get()
            browser_launcher = {
                "chromium": pw.chromium,
                "firefox": pw.firefox,
                "webkit": pw.webkit
            }.get(self.browser_type, pw.chromium)

            user_data_dir = self.profile_dir or os.path.join(os.getcwd(), ".wa_profile")
            os.makedirs(user_data_dir, exist_ok=True)

            try:
                self._context = browser_launcher.launch_persistent_context(
                    user_data_dir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 700}
                )
            except PlaywrightError as e:
                self._context = None
                raise RuntimeError(f"Playwright launch failed: {e}")

        # reuse or open a page
        try:
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = self._context.new_page()
        except Exception:
            # Attempt re-create context once
            try:
                if self._context:
                    try:
                        self._context.close()
                    except Exception:
                        pass
                self._context = None
                self._ensure_browser()
            except Exception as e:
                raise

        # ensure we are on whatsapp
        try:
            if "web.whatsapp.com" not in (self._page.url or ""):
                self._page.goto("https://web.whatsapp.com", timeout=60000)
            # wait for search box (signal that WA UI is ready)
            self._page.wait_for_selector('div[aria-label="Search input textbox"]', timeout=60000)
        except PlaywrightTimeoutError:
            # proceed — sometimes UI takes longer; caller will detect failures
            pass

    def _cleanup(self):
        try:
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None
            if PlaywrightManager._pw:
                # don't stop global playwright right away; keep it running for shared use
                try:
                    PlaywrightManager._pw = None
                except Exception:
                    pass
            self._page = None
        except Exception:
            self._context = None
            self._page = None

    # ---------------- helpers ----------------
    def _find_and_open_chat(self, contact_query: str, timeout: int = 20000) -> bool:
        """
        Uses WhatsApp Web search to find contact and open chat.
        More robust clearing of the search box and NO 'press Enter' fallback.
        Returns True if exact contact opened, False otherwise.
        """
        self._ensure_browser()
        page = self._page
        if not page:
            return False

        try:
            search_input = page.locator('div[aria-label="Search input textbox"]')
            search_input.wait_for(state="visible", timeout=10000)
        except Exception:
            return False

        try:
            # Robust clear: try fill(), else select-all + backspace, else DOM reset
            try:
                search_input.fill("")   # preferred
            except Exception:
                try:
                    search_input.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                except Exception:
                    try:
                        search_input.evaluate("el => el.innerText = ''")
                    except Exception:
                        pass

            # Focus + type
            search_input.click()
            search_input.type(contact_query, delay=80)
            time.sleep(1.5)  # wait results to populate

            # require exact span[title="..."] match — if not found, FAIL (do NOT open top result)
            contact_locator = page.locator(f'span[title="{contact_query}"]')
            try:
                contact_locator.wait_for(state="visible", timeout=4000)
                contact_locator.first.click()
                # wait for message box ready
                page.wait_for_selector("footer div[contenteditable='true']", timeout=8000)
                return True
            except Exception:
                # Not found => clean the search box to avoid leftover and return False
                try:
                    search_input.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                except Exception:
                    try:
                        search_input.fill("")
                    except Exception:
                        pass
                return False

        except Exception:
            return False

    def _send_text(self, message: str) -> bool:
        """
        Type message into message box and click the visible send button (avoid relying on Enter).
        """
        page = self._page
        if not page:
            return False

        try:
            box = page.locator("footer div[contenteditable='true']")
            box.wait_for(state="visible", timeout=10000)

            # ensure focus and clear any draft
            box.click(force=True)
            try:
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
            except Exception:
                try:
                    box.fill("")
                except Exception:
                    pass

            # Type message and click send button (new DOM uses a button with data-icon)
            page.keyboard.type(message, delay=25)
            time.sleep(0.2)

            # Prefer clicking the send button (safer than Enter in contenteditable)
            send_button = page.locator('button:has(span[data-icon="send"]), button:has(span[data-icon="wds-ic-send-filled"])')
            try:
                send_button.wait_for(state="visible", timeout=5000)
                send_button.first.click(force=True)
            except Exception:
                # fallback to Enter if send button not found
                page.keyboard.press("Enter")

            # Wait for the outgoing bubble to appear and check for error icon
            bubble = page.locator("div.message-out").last
            bubble.wait_for(timeout=10000)
            # detect failure icon inside bubble (msg-error)
            try:
                if bubble.locator('svg[data-icon="msg-error"]').count():
                    return False
            except Exception:
                pass

            # small pause to let WhatsApp finish
            time.sleep(0.6)
            return True
        except Exception:
            return False

    def can_handle(self, command: Command) -> bool:
        """
        WhatsAppSkill handles application-level send_message intents
        where app is whatsapp (explicit or implicit).
        """
        if not command or not hasattr(command, "intent"):
            return False

        if command.intent != "send_message":
            return False

        if command.domain != "application":
            return False

        ents = command.entities or {}

        # Explicit whatsapp mention OR implicit default
        app = (ents.get("app") or "").lower()
        if app and app != "whatsapp":
            return False

        # Required fields for WhatsApp
        if not ents.get("contact"):
            return False
        if not (ents.get("text") or ents.get("message")):
            return False

        return True

    # ---------------- public execute ----------------
    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        contact = (command.entities or {}).get("contact") or (command.entities or {}).get("to")
        text = (command.entities or {}).get("text") or (command.entities or {}).get("message")

        if not text:
            return SkillResult(False, "No text provided")
        if not contact:
            return SkillResult(False, "No contact provided")

        # resolve contact from registry or accept phone number
        cinfo = self.contacts.get(contact) or next(
            (v for k, v in self.contacts.items() if k.lower() == str(contact).lower()), None
        )
        if cinfo:
            contact_query = cinfo.get("whatsapp_name") or cinfo.get("name") or cinfo.get("phone") or contact
        else:
            s = str(contact).strip()
            if re.sub(r'\D', '', s).isdigit() and len(re.sub(r'\D', '', s)) >= 7:
                contact_query = s
            else:
                # if it looks like a phrase (e.g., "my friend X again"), keep as cleaned name
                contact_query = re.sub(r'^(my\s+friend\s+|my\s+pal\s+)', '', s, flags=re.I).strip()

        try:
            # If page/context died earlier, _ensure_browser will recreate
            opened = self._find_and_open_chat(contact_query)
            if not opened:
                return SkillResult(False, f"Contact '{contact_query}' not found", {"contact_query": contact_query})

            sent = self._send_text(text)
            if not sent:
                return SkillResult(False, "Failed to send message (send action failed)")

            return SkillResult(True, f"Message sent to {contact_query}", {"text": text, "contact_query": contact_query})
        except Exception as e:
            # If a browser/context was closed mid-execution, cleanup and report failure
            try:
                self._cleanup()
            except Exception:
                pass
            return SkillResult(False, f"Exception during send: {e}")
        finally:
            if self.close_on_finish:
                try:
                    self._cleanup()
                except Exception:
                    pass