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
- Playwright sync API is run in a dedicated worker thread to avoid "Sync API inside asyncio loop" errors
  when the pipeline runs in an environment that has an asyncio event loop (e.g. Cursor, some IDEs).
"""

# skills/whatsapp_skill.py
import time
import json
import re
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Dict, Any, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

# Thread-local state for Playwright in the worker thread (avoids asyncio conflict on main thread)
_worker_tls = threading.local()

def _get_worker_state():
    """Return Playwright state for current thread; None if not in worker or not yet initialized."""
    return getattr(_worker_tls, "state", None)

class PlaywrightManager:
    """
    Playwright MUST be thread-local.
    Never share Playwright instances across threads.
    """
    @staticmethod
    def get():
        ws = _get_worker_state()
        if ws is None:
            raise RuntimeError("PlaywrightManager.get() called outside worker thread")

        if not getattr(ws, "pw", None):
            ws.pw = sync_playwright().start()

        return ws.pw


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
        # Single-thread executor so all Playwright sync API runs in one thread (no asyncio loop there)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wa_playwright")

    def _state(self):
        """Return (context, page) from worker thread state or from self (main thread / legacy)."""
        ws = _get_worker_state()
        if ws is not None:
            return ws.context, ws.page
        return self._context, self._page

    # ---------- page/context health helpers ----------
    def _is_context_alive(self) -> bool:
        context, _ = self._state()
        if not context:
            return False
        try:
            _ = context.pages
            return True
        except Exception:
            return False

    def _ensure_browser(self):
        context, page = self._state()
        ws = _get_worker_state()
        # If context dead, recreate it
        if not self._is_context_alive():
            pw = PlaywrightManager.get()
            browser_launcher = {
                "chromium": pw.chromium,
                "firefox": pw.firefox,
                "webkit": pw.webkit
            }.get(self.browser_type, pw.chromium)

            user_data_dir = self.profile_dir or os.path.join(os.getcwd(), ".wa_profile")
            os.makedirs(user_data_dir, exist_ok=True)

            try:
                context = browser_launcher.launch_persistent_context(
                    user_data_dir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 700}
                )
            except PlaywrightError as e:
                if ws:
                    ws.context = None
                else:
                    self._context = None
                raise RuntimeError(f"Playwright launch failed: {e}")

            if ws is not None:
                ws.pw = pw
                ws.context = context
                ws.page = None
            else:
                self._context = context
                self._page = None

        context, _ = self._state()
        try:
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()
            if ws is not None:
                ws.page = page
            else:
                self._page = page
        except Exception:
            try:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
                if ws is not None:
                    ws.context = None
                    ws.page = None
                else:
                    self._context = None
                    self._page = None
                self._ensure_browser()
            except Exception as e:
                raise

        _, page = self._state()
        try:
            if "web.whatsapp.com" not in (page.url or ""):
                page.goto("https://web.whatsapp.com", timeout=60000)
            page.wait_for_selector(
                'div[aria-label="Search input textbox"], canvas[aria-label="Scan me!"]',
                timeout=60000
            )

        except PlaywrightTimeoutError:
            pass

    def _cleanup(self):
        """Clean up browser. If called from main thread, run cleanup in worker thread."""
        ws = _get_worker_state()
        if ws is not None:
            target_context = ws.context
            try:
                if target_context:
                    try:
                        target_context.close()
                    except Exception:
                        pass
                ws.context = None
                ws.page = None
            except Exception:
                ws.context = None
                ws.page = None
        else:
            # Main thread: ask worker thread to close its browser
            try:
                self._executor.submit(self._cleanup_in_worker).result(timeout=10)
            except Exception:
                pass
            self._context = None
            self._page = None
            pass

    # ---------------- helpers ----------------
    def _find_and_open_chat(self, contact_query: str, timeout: int = 20000) -> bool:
        """
        Uses WhatsApp Web search to find contact and open chat.
        Returns True if exact contact opened, False otherwise.
        This function is more robust: exact -> contains -> first-result fallback.
        """
        self._ensure_browser()
        _, page = self._state()
        if not page:
            return False

        try:
            search_input = page.locator('div[aria-label="Search input textbox"]')
            search_input.wait_for(state="visible", timeout=10000)
        except Exception:
            return False

        try:
            # robust clear
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

            search_input.click()
            # type slowly so WA can show suggestions
            search_input.type(contact_query, delay=80)
            time.sleep(1.2)  # let results populate

            # 1) Exact title match (strict)
            contact_locator = page.locator(f'span[title="{contact_query}"]')
            try:
                contact_locator.wait_for(state="visible", timeout=3000)
                contact_locator.first.click()
                page.wait_for_selector("footer div[contenteditable='true']", timeout=8000)
                return True
            except Exception:
                # not exact -> continue to fallback
                pass

            # 2) Case-insensitive contains() on title attribute (handles "Gautam Sharma (You)")
            try:
                # construct lowercase comparison using XPath translate()
                low = contact_query.lower()
                # use XPath: look for span whose title lowercased contains the query
                contains_xpath = (
                    f'//span[contains(translate(@title,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "{low}")]'
                )
                contains_loc = page.locator(f'xpath={contains_xpath}')
                if contains_loc.count() > 0:
                    contains_loc.first.click()
                    page.wait_for_selector("footer div[contenteditable='true']", timeout=8000)
                    return True
            except Exception:
                pass

            # 3) First-result fallback *only* if results list has visible options
            try:
                # common result item list container
                results = page.locator('div[role="list"] div[role="option"], div[role="listbox"] div[role="option"]')
                if results.count() == 1:
                    results.first.click()
                    page.wait_for_selector("footer div[contenteditable='true']", timeout=8000)
                    return True
            except Exception:
                pass

            # No match -> clear search box to avoid leftover text and return False
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
        _, page = self._state()
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

    def _cleanup_in_worker(self):
        """Run in worker thread to close browser/context held in thread-local state."""
        state = _get_worker_state()
        if state and getattr(state, "context", None):
            try:
                state.context.close()
            except Exception:
                pass
            state.context = None
            state.page = None

    def _do_send_in_thread(self, contact_query: str, text: str) -> SkillResult:
        """
        Run Playwright (sync API) in this worker thread only.
        Avoids "Sync API inside asyncio loop" when the main thread has an event loop.
        """
        if _get_worker_state() is None:
            _worker_tls.state = SimpleNamespace(pw=None, context=None, page=None)
        try:
            opened = self._find_and_open_chat(contact_query)
            if not opened:
                return SkillResult(False, f"Contact '{contact_query}' not found", {"contact_query": contact_query})
            sent = self._send_text(text)
            if not sent:
                return SkillResult(False, "Failed to send message (send action failed)")
            return SkillResult(True, f"Message sent to {contact_query}", {"text": text, "contact_query": contact_query})
        except Exception as e:
            return SkillResult(False, f"Exception during send: {e}")
        finally:
            if self.close_on_finish:
                try:
                    self._cleanup()
                except Exception:
                    pass

    # ---------------- public execute ----------------
    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        contact = (command.entities or {}).get("contact") or (command.entities or {}).get("to")
        text = (command.entities or {}).get("text") or (command.entities or {}).get("message")

        if not text:
            return SkillResult(False, "No text provided")
        if not contact:
            return SkillResult(False, "No contact provided")

        # resolve contact from registry or accept phone number (main thread)
        cinfo = self.contacts.get(contact) or next(
            (v for k, v in self.contacts.items() if k.lower() == str(contact).lower()), None
        )
        contact_query = None
        if cinfo:
            contact_query = cinfo.get("whatsapp_name") or cinfo.get("name") or cinfo.get("phone") or contact
        else:
            s = str(contact).strip()
            s_clean = re.sub(r'\s*\(.*\)$', '', s).strip()
            digits = re.sub(r'\D', '', s_clean)
            if digits and len(digits) >= 7:
                contact_query = digits
            else:
                matches = []
                qlow = s_clean.lower()
                for k, v in self.contacts.items():
                    if qlow == k.lower() or qlow in k.lower() or k.lower() in qlow:
                        matches.append((k, v))
                if len(matches) == 1:
                    k, v = matches[0]
                    contact_query = v.get("whatsapp_name") or v.get("name") or v.get("phone") or k
                elif len(matches) > 1:
                    return SkillResult(False, "Ambiguous contact; multiple matches", {"candidates": [m[0] for m in matches]})
                else:
                    contact_query = s_clean

        # Run all Playwright sync API in a dedicated thread (no asyncio loop there)
        try:
            future = self._executor.submit(self._do_send_in_thread, contact_query, text)
            return future.result(timeout=120)
        except Exception as e:
            if contact_query is None:
                # helpful debug for developer
                return SkillResult(False, f"Contact '{contact}' not found", {"contact_query": contact})

            return SkillResult(False, f"Exception during send: {e}")