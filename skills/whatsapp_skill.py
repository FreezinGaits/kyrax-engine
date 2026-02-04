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
    # ---------- UI state helpers ----------
    def _ensure_home_view(self, timeout: int = 5000):
        """
        Ensure WA is in main chat list / search-ready state.
        Safe to call before any search/send.
        """
        _, page = self._state()
        if page is None:
            return
        try:
            # try multiple back selectors (WhatsApp DOM varies)
            back_selectors = [
                "span[data-icon='back']",
                "span[data-icon='back-refreshed']",
                "button[aria-label='Back']",
                "button[title='Back']"
            ]
            for sel in back_selectors:
                try:
                    back = page.locator(sel)
                    if back.count() and back.is_visible():
                        back.first.click()
                        page.wait_for_timeout(250)
                        break
                except Exception:
                    pass

            # clear the search box safely
            self._clear_search()
        except Exception:
            # non-fatal: best-effort
            pass

    def _clear_search(self):
        """
        Clear WhatsApp search input with multiple fallbacks.
        """
        _, page = self._state()
        if page is None:
            return
        try:
            # Preferred: explicit clear icon (ic-close / x-alt)
            candidates = [
                'span[data-icon="x-alt"]',
                "button[aria-label='Clear search']",
                "xpath=//svg[title()='ic-close']",
                "xpath=//span[.//svg and contains(@class,'ic-close')]"  # fallback
            ]
            for sel in candidates:
                try:
                    el = page.locator(sel)
                    if el.count() and el.is_visible():
                        el.first.click()
                        page.wait_for_timeout(120)
                        return
                except Exception:
                    continue

            # Last-resort: clear input with keyboard
            try:
                inp = page.locator('div[aria-label="Search input textbox"]')
                if inp.count():
                    inp.first.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(120)
            except Exception:
                pass
        except Exception:
            pass

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
        # ensure page is on web.whatsapp.com and a search/scan UI is present
        try:
            if "web.whatsapp.com" not in (page.url or ""):
                page.goto("https://web.whatsapp.com", timeout=60000)
            try:
                page.wait_for_selector('div[aria-label="Search input textbox"], canvas[aria-label="Scan me!"]', timeout=60000)
            except Exception as e:
                # If the page/context got closed while waiting, attempt one recovery: recreate browser context
                # (helps when user manually closed the browser window)
                try:
                    # gently close stale context if possible
                    if context:
                        try:
                            context.close()
                        except Exception:
                            pass
                    # reset thread-local state -> force re-create on next call
                    if ws is not None:
                        ws.context = None
                        ws.page = None
                    else:
                        self._context = None
                        self._page = None
                    # re-run initialization once
                    return self._ensure_browser()
                except Exception:
                    # give up; caller should handle
                    pass
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
    def resolve_contact_via_whatsapp_ui(self, name: str, wait_ms: int = 1200) -> list[str]:
        """
        Returns list of matching chat titles.
        """
        self._ensure_browser()
        _, page = self._state()
        if not page:
            return []

        self._ensure_home_view()

        search_input = page.locator('div[aria-label="Search input textbox"]')
        search_input.first.click()
        search_input.first.type(name, delay=60)
        page.wait_for_timeout(wait_ms)

        titles = []
        results = page.locator(
            'div[role="list"] span[title]'
        )
        titles = []
        for i in range(results.count()):
            t = results.nth(i).get_attribute("title")
            if not t:
                continue

            t = t.strip()

            # ❌ ignore obvious non-contacts
            if t.lower() in {
                "message yourself",
                "archived",
            }:
                continue

            # ❌ ignore pure messages / emojis / very long junk
            if len(t) > 40:
                continue

            titles.append(t)



        self._clear_search()
        return list(set(titles))

    def save_contact(self, name: str, info: Optional[Dict[str,Any]] = None):
        """
        Add to in-memory contacts and persist to data/contacts.json.
        User must confirm before calling this.
        """
        info = info or {"whatsapp_name": name, "source": "ui_discovered"}
        self.contacts[name] = info
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/contacts.json", "w", encoding="utf-8") as f:
                json.dump(self.contacts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


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
    
    # add this helper method to your WhatsAppSkill class (place it near other helpers)
    def _resolve_contact_in_worker(self, name: str, wait_ms: int = 1200) -> list[str]:
        """
        Ensure worker thread-local Playwright state exists and then call the UI resolver.
        This avoids calling resolve_contact_via_whatsapp_ui from a worker thread that
        has no _worker_tls.state initialized.
        """
        # ensure worker thread-local state exists (the worker thread is the executor thread)
        if _get_worker_state() is None:
            _worker_tls.state = SimpleNamespace(pw=None, context=None, page=None)
        # now call the actual resolver (it will use thread-local state / create browser as needed)
        return self.resolve_contact_via_whatsapp_ui(name, wait_ms=wait_ms)

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

    def _do_send_in_thread(self, contact_query: str, text: str, ui_resolved: bool = False) -> SkillResult:
        """
        Run Playwright (sync API) in this worker thread only.
        Handles:
        - browser/page accidentally closed
        - UI state reset (archived / open chat / stale search)
        - one safe retry if WhatsApp was closed
        """

        # Ensure thread-local state exists
        if _get_worker_state() is None:
            _worker_tls.state = SimpleNamespace(pw=None, context=None, page=None)

        try:
            # 1️⃣ Ensure browser + page exist (reopens WhatsApp if user closed it)
            try:
                self._ensure_browser()
            except Exception as e:
                return SkillResult(
                    False,
                    f"Failed to start WhatsApp Web: {e}"
                )

            # 2️⃣ Ensure we are in HOME view (not archived, not inside a chat)
            try:
                self._ensure_home_view()
            except Exception:
                # Non-fatal; continue best-effort
                pass

            # 3️⃣ Try to open chat (FIRST ATTEMPT)
            if ui_resolved:
                opened = True  # chat already resolved by UI
            else:
                opened = self._find_and_open_chat(contact_query)


            # 4️⃣ If chat not opened, assume page/context was closed or stale → RECOVER ONCE
            if not opened:
                try:
                    # Hard reset: recreate browser context
                    try:
                        self._cleanup()
                    except Exception:
                        pass

                    # Reopen WhatsApp Web
                    self._ensure_browser()
                    self._ensure_home_view()

                    # Retry opening chat ONCE
                    opened = self._find_and_open_chat(contact_query)

                except Exception:
                    opened = False

            if not opened:
                return SkillResult(
                    False,
                    f"Contact '{contact_query}' not found or WhatsApp not ready",
                    {"contact_query": contact_query}
                )

            # 5️⃣ Send the message
            sent = self._send_text(text)
            if not sent:
                return SkillResult(
                    False,
                    "Failed to send message (send action failed)"
                )

            # Persist new contact AFTER successful send

            # ✅ Save contact if:
            # - message was sent
            # - AND contact not already saved
            if contact_query not in self.contacts:
                self.save_contact(
                    contact_query,
                    {
                        "name": contact_query,
                        "whatsapp_name": contact_query,
                        "source": "ui_auto_saved"
                    }
                )



            return SkillResult(
                True,
                f"Message sent to {contact_query}",
                {"text": text, "contact_query": contact_query}
            )


        except Exception as e:
            return SkillResult(
                False,
                f"Exception during send: {e}"
            )

        finally:
            # Optional cleanup if configured
            if self.close_on_finish:
                try:
                    self._cleanup()
                except Exception:
                    pass

    
    # ---------------- public execute ----------------
    def execute(self, command: Command, context: Optional[Dict[str, Any]] = None) -> SkillResult:
        contact = (command.entities or {}).get("contact") or (command.entities or {}).get("to")
        text = (command.entities or {}).get("text") or (command.entities or {}).get("message")
        ui_resolved = False
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
            
            # if contact not canonicalized by contacts.json, try UI resolution (best-effort)
            # 🔥 ALWAYS try UI resolution when name is not an exact saved key
            # try:
            #     # new: ensure thread-local initialized inside worker and call resolver there
            #     ui_matches = self._executor.submit(
            #         self._resolve_contact_in_worker, contact_query
            #     ).result(timeout=12)


            #     if not ui_matches:
            #         return SkillResult(
            #             False,
            #             f"No WhatsApp contact found for '{contact_query}'."
            #         )

            #     if len(ui_matches) > 1:
            #         return SkillResult(
            #             False,
            #             "Multiple contacts found with this name. Please specify the full name.",
            #             {"candidates": ui_matches}
            #         )

            #     # ✅ EXACTLY ONE MATCH
            #     contact_query = ui_matches[0]
            #     ui_resolved = True

            # except Exception:
            #     pass



        # Run all Playwright sync API in a dedicated thread (no asyncio loop there)
        try:
            future = self._executor.submit(self._do_send_in_thread, contact_query, text, ui_resolved)
            return future.result(timeout=120)
        except Exception as e:
            if contact_query is None:
                # helpful debug for developer
                return SkillResult(False, f"Contact '{contact}' not found", {"contact_query": contact})

            return SkillResult(False, f"Exception during send: {e}")