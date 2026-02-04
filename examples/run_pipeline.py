"""
examples/run_pipeline.py

Full KYRAX pipeline integrating:
 - LLM Adapters (Gemini/OpenAI abstraction via llm_adapters.py)
 - LLMNLU (Gemini-backed natural language understanding)
 - AIReasoner (multi-step planning for compound goals)
 - ChainExecutor (sequential execution with placeholder resolution)
 - CommandBuilder (validation + normalization with ContactResolver)
 - ContextLogger (short-term memory for agentic behavior)
 - WorkflowStore (SQLite persistence for workflows)
 - Dispatcher -> SkillRegistry -> Skills (WhatsApp, OS, IoT)

Pipeline Flow:
 1. Fast path: Direct send parser (bypasses LLM for simple "send to X saying Y")
 2. Compound: AIReasoner → ChainExecutor → Dispatcher (multi-step with data dependencies)
 3. Single: LLMNLU → CommandBuilder → Dispatcher (single intent execution)

Notes:
 - Requires GEMINI_API_KEY environment variable for LLM features
 - Ensure data/contacts.json exists with your contacts
 - WhatsApp profile directory: set WHATSAPP_PROFILE_DIR env var or edit code
 - OS skill runs in dry_run mode by default (set KYRAX_OS_DRY_RUN=false to enable)
 - Workflows are persisted to kyrax_workflows.db (SQLite)
"""

import os
import time
import logging
import json
import re
from typing import List
# if os.environ.get("KYRAX_MODE", "").lower() == "regex":
#     os.environ.pop("GEMINI_API_KEY", None)
#     os.environ.pop("GOOGLE_API_KEY", None)

# core pipeline pieces
# use LLM adapter abstraction (Gemini-backed)
# from kyrax_core.llm_adapters import get_llm_callable, gemini_llm_callable
# from kyrax_core.llm.gemini_client import GeminiClient  # Still needed for LLMNLU
# from kyrax_core.nlu.llm_nlu import LLMNLU
from kyrax_core.intent_mapper import map_nlu_to_command
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.context_logger import ContextLogger
from kyrax_core.skill_registry import SkillRegistry
from kyrax_core.dispatcher import Dispatcher
from kyrax_core.command import Command
# from kyrax_core.ai_reasoner import AIReasoner
from kyrax_core.chain_executor import ChainExecutor
from kyrax_core.workflow_manager import WorkflowStore, STATUS_COMPLETED, STATUS_FAILED
# utils we added
from kyrax_core.contact_resolver import ContactResolver

# skills
from skills.whatsapp_skill import WhatsAppSkill
from skills.os_skill import OSSkill
from skills.iot_skill import IoTSkill

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("run_pipeline")
# ---------- Execution policy (single canonical flow) ----------
# Regex is ALWAYS first.
USE_REGEX = True

# LLM is used ONLY if regex fails AND API key exists
USE_LLM = bool(
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)

# diagnostic: print env detection immediately so we can see what's visible to Python
print("=== LLM env detection (startup) ===")
print("GEMINI_API_KEY present:", bool(os.environ.get("GEMINI_API_KEY")))
print("OPENAI_API_KEY present:", bool(os.environ.get("OPENAI_API_KEY")))
print("GOOGLE_API_KEY present:", bool(os.environ.get("GOOGLE_API_KEY")))
# Also show short prefixes so we can confirm value (safe: print only first 8 chars)
print("GEMINI prefix:", (os.environ.get("GEMINI_API_KEY") or "")[:8])
print("OPENAI prefix:", (os.environ.get("OPENAI_API_KEY") or "")[:8])
print("GOOGLE prefix:", (os.environ.get("GOOGLE_API_KEY") or "")[:8])
print("Computed USE_LLM =", USE_LLM)
print("==================================")


# If LLM fails, we DO NOT guess with regex again
REGEX_FALLBACK_IF_LLM_UNAVAILABLE = False

log.debug(
    "Execution policy: USE_REGEX=%s, USE_LLM=%s",
    USE_REGEX, USE_LLM
)
# -------------------------------------------------------------

GeminiClient = None
LLMNLU = None
AIReasoner = None

if USE_LLM:
    from kyrax_core.llm.gemini_client import GeminiClient
    from kyrax_core.nlu.llm_nlu import LLMNLU
    from kyrax_core.ai_reasoner import AIReasoner

# -------------------------
# Helper clause splitter
# -------------------------
def extract_multiple_contacts(raw: str, resolver):
    """
    Extract multiple contacts using ContactResolver.
    Returns a list of resolved contact names.
    """
    names = []
    tokens = re.split(r'\band\b|,', raw, flags=re.I)
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # Ask resolver for best match
        cands = resolver.candidates(t, n=1, cutoff=0.4)
        if cands:
            names.append(cands[0][0])
        else:
            names.append(t)  # fallback to raw token
    return list(dict.fromkeys(names))  # dedupe, preserve order

def _looks_like_suspect_contact(contact: str) -> bool:
    """
    Return True if contact string looks suspicious (likely not a real contact).
    Conservative: only mark as suspect when clearly not a name/phone.
    """
    if not contact:
        return True
    low = contact.strip().lower()

    # obvious verb/command tokens are suspect
    if low in ("message", "text", "send", "share", "ask", "tell"):
        return True

    # phone-like numeric token: accept if length >= 7 (reasonable phone)
    if re.fullmatch(r'\d+', low):
        return False if len(low) >= 7 else True

    # single-token numeric-ish or punctuation-only -> suspect
    if re.fullmatch(r'[^a-zA-Z0-9]+', low):
        return True

    # very short tokens (1-2 characters) are suspicious (e.g., "ok", "hi")
    if len(low) <= 2:
        return True

    # otherwise assume it's probably OK (name-like)
    return False


def is_safe_for_regex_execution(raw: str) -> bool:
    """
    Strict semantic gate for deterministic execution.
    Regex execution is allowed ONLY for trivial, unambiguous,
    single-domain send-text commands, including fan-out shorthand:

      - send alice hi
      - send alice hi and bob hello
      - send hi to alice and hello to bob

    Rejects subordinate clauses, questions, mixed-domain verbs, pronouns, and long/clausey inputs.
    """
    if not raw or not raw.strip():
        return False

    s = raw.strip()
    s_l = s.lower()

    # Quick rejects: subordinate / explanatory / interrogative / politeness forms
    if re.search(r'\b(that|if|whether|who|what|when|why|could you|would you|please|do you)\b', s_l):
        return False
    if "?" in s:
        return False

    # Mixed-domain verbs (open/launch/turn/play etc.) are not allowed in deterministic send mode
    if re.search(r'\b(open|launch|turn on|turn off|start|close|play|stop)\b', s_l):
        return False

    # Must contain a send-like verb somewhere (conservative)
    if not re.search(r'\b(send|text|message|notify|ping|to)\b', s_l):
        return False

    # Limit length to avoid greedy captures
    if len(s.split()) > 30:
        return False

    # ----- Fan-out handling: allow shorthand on subsequent clauses -----
    if " and " in s_l:
        clauses = [c.strip() for c in re.split(r'\band\b', s, flags=re.I) if c.strip()]
        if not clauses:
            return False

        # First clause MUST be a send/text/message style command (explicit)
        if not re.match(r'^(send|text|message)\b', clauses[0].lower()):
            return False

        # Validate subsequent clauses conservatively:
        for c in clauses[1:]:
            c_l = c.lower()
            # Allowed forms for subsequent clauses:
            # 1) explicit send/text/message ... (safe)
            if re.match(r'^(send|text|message)\b', c_l):
                continue
            # 2) "<contact> <message>" shorthand where contact is short (<=4 tokens) and message non-empty
            m = re.match(r'^(?P<contact>[A-Za-z0-9 _\-\+]{1,60})\s+(?P<msg>.+)$', c)
            if m:
                contact = m.group("contact").strip()
                msg = m.group("msg").strip()
                if 0 < len(msg) <= 200 and len(contact.split()) <= 4:
                    # message part must NOT contain subordinate/question words
                    if not re.search(r'\b(that|if|whether|who|what|when|why)\b|\?', msg.lower()):
                        continue
            # 3) "<text> to <contact>" form e.g., "hello to gautam"
            if re.match(r'^.+\s+to\s+[^,;]+$', c_l):
                # be conservative: ensure 'to' isn't at the very start (that's separate)
                continue

            # If none of the allowed patterns matched -> unsafe
            return False

    # For single-clause inputs (no 'and'): ensure starts with send|text|message or is short shorthand with clear structure
    else:
        s_stripped = s.strip()
        if re.match(r'^(send|text|message)\b', s_l):
            # ok
            pass
        else:
            # Allow short shorthand like "alice hi" OR "hi to alice" (<= 2-3 tokens for contact)
            m = re.match(r'^(?P<contact>[A-Za-z0-9 _\-\+]{1,60})\s+(?P<msg>.+)$', s_stripped)
            if m:
                contact = m.group("contact").strip()
                msg = m.group("msg").strip()
                if not (0 < len(msg) <= 200 and len(contact.split()) <= 4):
                    return False
            else:
                return False

    return True


def looks_like_direct_send(raw: str) -> bool:
    """
    Return True only for clear imperative 'send/text' commands that are
    almost certainly single-step direct sends and safe to run without LLM.
    Be conservative: if the sentence contains subordinating words (that/if/whether)
    or question marks or long/clausey phrasing, return False so LLM can handle it.
    """
    if not raw or not raw.strip():
        return False
    s = raw.strip()
    s_l = s.lower()

    # Quick rejects: explicit subordinate clauses or question-like inputs
    if " that " in s_l or " if " in s_l or " whether " in s_l or " who " in s_l or " what " in s_l or " when " in s_l or " why " in s_l:
        return False
    if "?" in s:
        return False
    if s_l.startswith(("ask ", "tell ", "please ", "could ", "would ")):
        return False

    # Must start with a send/text style verb OR be a clause that looks like "to X saying Y"
    start_ok = any(s_l.startswith(p) for p in ("send ", "text ", "message ", "whatsapp ", "to "))
    if not start_ok:
        return False

    # Strong positive indicator: presence of the keyword 'saying' (explicit direct content)
    if re.search(r'\bsaying\b', s_l):
        return True

    # Conservative fallback: short sentences (<= 7 tokens) that start with send/text/message
    tokens = s_l.split()
    if len(tokens) <= 7 and any(s_l.startswith(pref) for pref in ("send ", "text ", "message ")):
        return True

    # Anything longer or clausey → do not fast-path
    return False

def resolve_contact_reference(contact: str, ctx_logger):
    """
    Resolve references like 'previous contact', 'last contact'.
    """
    if not contact:
        return contact

    c = contact.lower().strip()
    if c in ("previous contact", "last contact", "previous one", "last one"):
        if ctx_logger:
            last = ctx_logger.get_most_recent("last_contact")
            if last:
                return last
    return contact


def split_clauses(raw: str) -> List[str]:
    parts = re.split(r'\b(?:and then|then|, then|,|;|\band\b|\bthen\b)\b', raw, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def extract_send_commands(raw: str):
    """
    Conservative extractor returning list of dicts {contact, text}.
    Handles:
      - send alice saying hi
      - send hi to alice
      - send alice hi
      - alice: hi
      - to alice hi
      - hi to alice
      - send hi to alice and hello to bob  (after fan-out)
      - send alice hi and bob hello
    """
    out = []
    if not raw or not raw.strip():
        return out
    # 🔧 NORMALIZE "saying" → ":" to avoid greedy regex corruption
    # "send to Akshat saying hi" → "send to Akshat: hi"
    normalized = re.sub(
        r'\bsaying\s+',
        ': ',
        raw,
        flags=re.I
    )

    s = normalized.strip()
    s = raw.strip()
    # split on commas/and/then but keep clause pieces
    clauses = re.split(r',\s*|\s+\band\b\s+|\s+\band then\b\s+|\s+\bthen\b\s+', s, flags=re.I)

    for c in clauses:
        c = c.strip()
        if not c:
            continue

        # shorthand: "to Alice hi" -> "to <contact> <text>"
        if c.lower().startswith("to "):
            m = re.match(r'^to\s+(?P<contact>[A-Za-z0-9 _\-\+]{1,60}?)\s+(?P<text>.+)$', c, flags=re.I)
            if m:
                out.append({"contact": m.group("contact").strip(), "text": m.group("text").strip()})
            continue

        # pattern: "send a message to Alice saying hi" OR "message Alice: hi" OR "message Alice, hi"
        m = re.search(
            r'^(?:send\s+(?:a\s+message\s+)?)?(?:message|text|notify|ping)\s+(?P<contact>[^:,\-]+?)[\s,:-]+\s*(?P<text>.+)$',
            c, flags=re.I
        )
        if m:
            out.append({"contact": m.group("contact").strip(), "text": m.group("text").strip()})
            continue

        # pattern: "send hi to Alice" or "text hi to Alice" OR "hi to alice"
        m = re.search(r'^(?:send|text|message)?\s*(?P<text>.+?)\s+to\s+(?P<contact>[^,;]+)$', c, flags=re.I)
        if m:
            out.append({"contact": m.group("contact").strip(), "text": m.group("text").strip()})
            continue

        # pattern: "send Alice hi" or "Alice hi" (shorthand contact first)
        m = re.search(r'^(?:send\s+)?(?P<contact>[A-Za-z0-9 _\-\+]{1,60}?)\s+[,\-]?\s*(?P<text>.+)$', c, flags=re.I)
        if m:
            contact = m.group("contact").strip()
            text = m.group("text").strip()
            # conservative checks to avoid greedy capture
            if contact and text and len(contact.split()) <= 4 and 0 < len(text) <= 200:
                if not re.search(r'\b(that|if|whether|who|what|when|why)\b|\?', text, flags=re.I):
                    out.append({"contact": contact, "text": text})
            continue

        # fallback: "Alice: hi" or "Alice - hi"
        m = re.match(r'^(?P<contact>[A-Za-z0-9 _\-\+]{1,60})\s*[:\-]\s*(?P<text>.+)$', c, flags=re.I)
        if m:
            contact = m.group("contact").strip()
            text = m.group("text").strip()
            if contact and text and len(text) <= 200:
                out.append({"contact": contact, "text": text})
            continue

    return out





# -------------------------
# Main CLI pipeline
# -------------------------
def main():
    print("Starting KYRAX pipeline (examples/run_pipeline.py)")
    print("=" * 60)

    # lazy-init LLM adapter (prevents import-time side-effects)
    llm_callable = None
    if USE_LLM:
        try:
            from kyrax_core.llm_adapters import get_llm_callable, gemini_llm_callable
            try:
                llm_callable = get_llm_callable(prefer="gemini")
                print("LLM adapter: get_llm_callable returned:", bool(llm_callable))
                # if llm_callable is a callable object, show repr
                if llm_callable:
                    try:
                        print("LLM adapter repr:", repr(llm_callable)[:200])
                    except Exception:
                        pass
            except Exception as e:
                import traceback
                print("get_llm_callable() raised an exception:")
                traceback.print_exc()
                llm_callable = None
        except Exception as e:
            import traceback
            log.warning("LLM adapter import failed (lazy): %s", e)
            print("LLM adapter import/initialization error:")
            traceback.print_exc()
            llm_callable = None




    if not llm_callable:
        # More explicit diagnostic output
        import traceback
        print("⚠️  Warning: No LLM callable created.")
        print("   Env keys present:",
            "GEMINI_API_KEY" if os.environ.get("GEMINI_API_KEY") else "",
            "OPENAI_API_KEY" if os.environ.get("OPENAI_API_KEY") else "")
        print("   Some features will be limited. Set GEMINI_API_KEY or OPENAI_API_KEY for full functionality.")
        # Optionally show any adapter import error stored in llm_callable_init_error if you capture it earlier.
        llm_callable = None


    # NLU: Still need GeminiClient directly for LLMNLU (can refactor later)
    gemini = None
    nlu = None
    if USE_LLM and llm_callable:
        try:
            gemini = GeminiClient()
            nlu = LLMNLU(gemini_client=gemini)
        except Exception as e:
            log.warning("Failed to initialize Gemini NLU: %s", e)
            nlu = None

    builder = CommandBuilder()
    ctx_logger = ContextLogger(max_entries=200, ttl_seconds=3600)
    registry = SkillRegistry()

    # Contact resolver
    resolver = ContactResolver("data/contacts.json")

    # AI reasoner (uses LLM adapter abstraction)
    reasoner = None
    if USE_LLM and llm_callable:
        reasoner = AIReasoner(llm=llm_callable)

    # Chain executor for multi-step tasks with data dependencies
    chain_executor = ChainExecutor(global_ctx={})

    # Workflow store for persistence (optional, can disable by setting to None)
    workflow_store = None
    try:
        workflow_store = WorkflowStore(path="kyrax_workflows.db")
        print("✓ Workflow persistence enabled")
    except Exception as e:
        log.warning("Workflow store initialization failed: %s (continuing without persistence)", e)

    # keep a flag/timer to avoid repeatedly hitting LLM when quota is exhausted
    llm_available = llm_callable is not None
    llm_disabled_until = 0.0
    LLM_DISABLE_DEFAULT = 60

    # Register skills
    wa_profile = os.environ.get("WHATSAPP_PROFILE_DIR", r"C:\Users\HP\kyrax_wa_profile")
    try:
        wa_skill = WhatsAppSkill(profile_dir=wa_profile, headless=False, close_on_finish=False, browser_type="chromium")
        registry.register(wa_skill)
        print("✓ WhatsApp skill registered")
    except Exception as e:
        log.warning("WhatsApp skill registration failed: %s", e)

    # Register OS skill (dry_run=True for safety, set to False to allow real app launches)
    os_skill = OSSkill(dry_run=os.environ.get("KYRAX_OS_DRY_RUN", "true").lower() == "true")
    registry.register(os_skill)
    print("✓ OS skill registered (dry_run={})".format(os_skill.dry_run))

    # Register IoT skill (simulated by default, pass MQTT client if available)
    iot_skill = IoTSkill(mqtt_client=None)  # Set mqtt_client if you have one
    registry.register(iot_skill)
    print("✓ IoT skill registered (simulated mode)")

    dispatcher = Dispatcher(registry=registry)
    print("=" * 60)
    print("KYRAX CLI ready. Type 'exit' to quit.")
    print("Examples:")
    print("  - send a message to Akshat saying hi")
    print("  - open chrome")
    print("  - turn on bedroom light")
    print("  - send to Akshat saying hi and to Gautam saying hello")

    print("KYRAX CLI (type 'exit' to quit). Example: send a message to Akshat: 'send a message to Akshat saying hi'")

    try:
        while True:
            try:
                raw = input("\n> ").strip()
                regex_consumed = False
            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break
            if not raw:
                continue
            if raw.lower() in ("exit", "quit"):
                break

            # ---- deterministic multi-send handler (MUST RUN FIRST) ----
            multi_cmds = extract_send_commands(raw)
            # HARD RULE: regex mode does NOT support mixed-domain commands
            # HARD BLOCK: no AI usage in regex mode
            # if MODE == "regex":
            #     if re.search(r'\b(could you|would you|please|ask if|that)\b', raw.lower()):
            #         print("❌ Regex mode cannot interpret conversational requests.")
            #         print("👉 Try a direct command, or switch: set KYRAX_MODE=auto")
            #         continue


            # Hard reject fan-out unless ALL clauses are send-like
            # Relaxed fan-out check: allow send-first + shorthand subsequent clauses
            s_l = raw.lower()
            if " and " in s_l:
                clauses = [c.strip() for c in re.split(r'\band\b', raw, flags=re.I) if c.strip()]
                if clauses:
                    # first clause must be explicit send/text/message
                    if not re.match(r'^(send|text|message)\b', clauses[0].lower()):
                        multi_cmds = []
                    else:
                        # leave multi_cmds intact; extract_send_commands will parse each clause
                        pass

            if multi_cmds and is_safe_for_regex_execution(raw) and USE_REGEX:

                if looks_like_direct_send(raw):
                    validated_cmds = []
                    regex_blocked = False

                    for step in multi_cmds:
                        nlu_like = {
                            "intent": "send_message",
                            "entities": {
                                "contact": resolve_contact_reference(step["contact"], ctx_logger),
                                "text": step["text"],
                            },
                            "confidence": 0.9,
                            "source": "local_parser",
                        }

                        try:
                            cmd, issues = builder.build(
                                nlu_like,
                                source="local_parser",
                                context_logger=ctx_logger,
                                raw_text=raw,
                                contacts_registry=resolver,
                            )
                        except TypeError:
                            cmd, issues = builder.build(
                                nlu_like,
                                source="local_parser",
                                context_logger=ctx_logger,
                            )

                        # if cmd and _looks_like_suspect_contact(cmd.entities.get("contact")):
                        #     issues = (issues or []) + ["suspect_contact"]

                        if issues:
                            # Only block on REAL structural issues, not heuristic ones
                            hard_issues = [
                                i for i in issues
                                if not i.startswith("suspect_")
                            ]
                            if hard_issues:
                                regex_blocked = True
                                break

                        validated_cmds.append(cmd)

                    # --- DECISION POINT ---
                    if regex_blocked:
                        log.info("Regex matched but execution unsafe — deferring entire input to LLM")
                        # DO NOT execute ANY regex steps
                    else:
                        print(f"Detected {len(validated_cmds)} send-message task(s) (local parser). Executing sequentially.")
                        for cmd in validated_cmds:
                            print("Executing:", cmd)
                            res = dispatcher.execute(cmd)
                            print("Result:", res)
                            if res.success:
                                ctx_logger.update_from_command(cmd)

                        regex_consumed = True
                        continue


                else:
                    # We detected potential send-like clauses but the input is not a clear direct send
                    # (e.g., "message Akshat that I'll be late" or "send my friend gautam asking if he's doing well").
                    # Let the LLM handle those complex forms (fall through to LLM path below).
                    pass
                # If regex matched but was NOT safe, fall through to LLM / Reasoner
                # if multi_cmds and not is_safe_for_regex_execution(raw):
                #     log.info("Regex matched but semantic gate failed — deferring to LLM.")

            # If user input looks like a multi-step compound, prefer AI Reasoner to propose a plan
            clauses = split_clauses(raw)
            is_compound = (
                len(clauses) > 1
                and not extract_send_commands(raw)
            )


            # If we have an LLM and the user wrote a compound sentence, ask reasoner for proposals
            if is_compound and USE_LLM and reasoner:

                try:
                    proposals = reasoner.propose_and_validate_plan(
                        raw, 
                        context=ctx_logger.get_all(), 
                        command_builder=builder, 
                        max_candidates=1
                    )
                except Exception as e:
                    log.warning("Reasoner proposal failed: %s", e)
                    proposals = []

                if proposals:
                    # proposals is list of tuples (PlanProposal, [(Command|None, issues), ...])
                    # PlanProposal.proposed_commands is the LLM's steps (not `steps`).
                    plan, validated = proposals[0]

                    # Normal form: plan.proposed_commands contains the proposed steps.
                    # Treat empty proposals or a single ask_clarify as "need clarification".
                    need_clarify = False
                    if not getattr(plan, "proposed_commands", None):
                        need_clarify = True
                    elif (
                        len(plan.proposed_commands) == 1
                        and getattr(plan.proposed_commands[0], "intent", "") == "ask_clarify"
                    ):
                        need_clarify = True

                    if need_clarify:
                        # prefer a question string from the plan or fall back to explanation
                        question = ""
                        if getattr(plan, "proposed_commands", None) and len(plan.proposed_commands) == 1:
                            question = plan.proposed_commands[0].entities.get("question", "")
                        print("🤖 I need clarification:")
                        print(question or plan.explanation or "Clarification required")
                        pass

                    # print(f"🤖 AI proposed plan: {plan.explanation} (score={plan.score:.2f})")
                    
                    # Extract validated commands (skip ones with issues)
                    commands_to_execute = []
                    for idx, (cmd_obj, issues) in enumerate(validated, start=1):
                        if issues:
                            print(f" ⚠️  Step {idx}: Skipped due to issues: {issues}")
                        elif cmd_obj:
                            commands_to_execute.append(cmd_obj)
                            print(f" ✓ Step {idx}: {cmd_obj.intent} -> {cmd_obj.entities}")
                    
                    if commands_to_execute:
                        # Use chain_executor for multi-step execution with placeholder resolution
                        if len(commands_to_execute) > 1:
                            print(f"\n📋 Executing {len(commands_to_execute)} steps sequentially...")
                            results, chain_issues = chain_executor.execute_chain(
                                commands_to_execute, 
                                dispatcher, 
                                stop_on_error=False
                            )
                            
                            # Report results
                            for idx, (result, cmd) in enumerate(zip(results, commands_to_execute), start=1):
                                if result.get("success", False):
                                    print(f" ✓ Step {idx} completed: {result.get('message', 'OK')}")
                                    ctx_logger.update_from_command(cmd)
                                else:
                                    print(f" ✗ Step {idx} failed: {result.get('message', 'Unknown error')}")
                            
                            if chain_issues:
                                print(f" ⚠️  Chain execution issues: {len(chain_issues)}")
                        else:
                            # Single command, execute directly
                            cmd_obj = commands_to_execute[0]
                            print(f" Executing: {cmd_obj}")
                            res = dispatcher.execute(cmd_obj)
                            print(" Result:", res)
                            if res.success:
                                ctx_logger.update_from_command(cmd_obj)
                        
                        # Persist workflow if store is available
                        if workflow_store:
                            try:
                                wf_id = workflow_store.create_workflow(raw, commands_to_execute)
                                workflow_store.mark_workflow_state(wf_id, "completed")
                                log.debug("Workflow persisted: %s", wf_id)
                            except Exception as e:
                                log.warning("Failed to persist workflow: %s", e)
                    
                    # After handling the plan, go to next user input
                    continue

            # --- Single-clause / fallback path: NLU -> map -> build -> dispatch
            # Call LLM-backed NLU only when llm_available and not temporarily disabled
            # Only invoke LLM when: LLM is enabled/available AND
            #   (a) the input is compound (multi-clause) OR
            #   (b) the strict regex gate rejected the input (not safe for regex execution).
            need_llm = (
                not regex_consumed
                and not is_safe_for_regex_execution(raw)
            )

            if USE_LLM and llm_available and time.time() >= llm_disabled_until and nlu and need_llm:

                try:
                    nlu_res = nlu.analyze(raw)
                except Exception as e:
                    # handle Resource Exhausted / rate limit specifically
                    msg = str(e)
                    if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower() or "Too Many Requests" in msg:
                        # disable LLM for a short period (backoff)
                        llm_available = False
                        llm_disabled_until = time.time() + LLM_DISABLE_DEFAULT
                        print("⚠️ AI quota exhausted or rate-limited — falling back to local parsing for now.")
                        log.warning("LLM temporarily disabled due to error: %s", e)
                        # Try to fallback to non-LLM parsing (regex) if configured to do so
                        if REGEX_FALLBACK_IF_LLM_UNAVAILABLE and USE_REGEX and multi_cmds:
                            print("⚠️ AI temporarily unavailable — attempting deterministic regex handling as fallback.")
                            # reuse your validated_cmds logic (preflight) — call the same preflight/execute steps
                            # we can reuse the existing "preflight / validated_cmds" flow by jumping to the same section.
                            # minimal, inline fallback: validate & execute deterministic multi_cmds
                            validated_cmds = []
                            regex_blocked = False
                            for step in multi_cmds:
                                nlu_like = {
                                    "intent": "send_message",
                                    "entities": {
                                        "contact": resolve_contact_reference(step["contact"], ctx_logger),
                                        "text": step["text"],
                                    },
                                    "confidence": 0.9,
                                    "source": "local_parser",
                                }
                                try:
                                    cmd, issues = builder.build(
                                        nlu_like,
                                        source="local_parser",
                                        context_logger=ctx_logger,
                                        raw_text=raw,
                                        contacts_registry=resolver,
                                    )
                                except TypeError:
                                    cmd, issues = builder.build(
                                        nlu_like,
                                        source="local_parser",
                                        context_logger=ctx_logger,
                                    )

                                # Only block on real issues (not 'suspect_' heuristics)
                                hard_issues = [i for i in (issues or []) if not i.startswith("suspect_")]
                                if hard_issues:
                                    regex_blocked = True
                                    break
                                validated_cmds.append(cmd)

                            if not regex_blocked and validated_cmds:
                                print(f"Detected {len(validated_cmds)} send-message task(s) (regex-fallback). Executing sequentially.")
                                for cmd in validated_cmds:
                                    res = dispatcher.execute(cmd)
                                    print("Result:", res)
                                    if getattr(res, "success", False):
                                        ctx_logger.update_from_command(cmd)
                                continue  # input consumed by regex fallback
                            else:
                                print("Regex fallback couldn't safely resolve the input. Please rephrase.")
                                continue
                        else:
                            # fallback not allowed -> skip / ask user
                            continue

                    else:
                        # Other LLM errors: log + fallback safely
                        log.exception("NLU LLM error: %s", e)
                        print("🤖 I can send a message for you.")
                        print("Please tell me:")
                        print("  - Who should receive the message?")
                        print("  - What should the message say?")
                        continue
            else:
                # LLM disabled: fallback behavior -> either do local parsing or prompt user to rephrase
                # We already attempted extract_send_commands earlier; at this point run a simpler deterministic parser or ask to rephrase.
                print("❌ I couldn't safely interpret that with deterministic rules.")
                print("👉 Try: send <name> <message> and <name> <message>")

                continue


            # 🔹 LLM multi-contact fan-out handling
            if nlu_res.get("intent") == "send_message":
                raw_text = raw.lower()

                # naive but safe split for "and"
                contacts = []
                if " and " in raw_text:
                    parts = re.split(r'\band\b', raw, flags=re.I)
                    for p in parts:
                        # try extracting a name-like token
                        m = re.search(r'\b([A-Z][a-z]+)\b', p)
                        if m:
                            contacts.append(m.group(1))

                # If multiple contacts detected → fan out
                if len(contacts) >= 2:
                    print(f"Detected {len(contacts)} recipients (LLM fan-out). Executing sequentially.")
                    for c in contacts:
                        nlu_like = {
                            "intent": "send_message",
                            "entities": {
                                "contact": c,
                                "text": nlu_res["entities"].get("text"),
                            },
                            "confidence": nlu_res.get("confidence", 0.9),
                            "source": "llm_fanout",
                        }

                        cmd, issues = builder.build(
                            nlu_like,
                            source="llm_fanout",
                            context_logger=ctx_logger,
                            raw_text=raw,
                            contacts_registry=resolver,
                        )

                        if issues:
                            print("Skipped due to issues:", issues)
                            continue

                        res = dispatcher.execute(cmd)
                        print("Result:", res)
                        if res.success:
                            ctx_logger.update_from_command(cmd)

                    continue  # IMPORTANT: stop normal single-command flow


            # Use the bridge to get a Command-like object
            # 🔥 LLM fan-out handling
            if nlu_res.get("intent") == "send_message":
                contacts = extract_multiple_contacts(raw, resolver)

                # ---- 🔒 UNKNOWN CONTACT GATE (PUT IT HERE) ----
                # unknown = [
                #     c for c in contacts
                #     if not resolver.candidates(c, n=1, cutoff=0.4)
                # ]

                # if unknown:
                #     print("🤖 I found some contacts I don't recognize:")
                #     for u in unknown:
                #         print(" -", u)
                #     print("Please add them to data/contacts.json or rephrase.")
                #     continue  # ⛔ STOP here — no execution
                # ----------------------------------------------

                # If multiple contacts → fan out
                if len(contacts) > 1:
                    print(f"Detected {len(contacts)} recipients (LLM fan-out). Executing sequentially.")

                    for contact in contacts:
                        nlu_like = {
                            "intent": "send_message",
                            "entities": {
                                "contact": contact,
                                "text": nlu_res["entities"].get("text"),
                            },
                            "confidence": nlu_res.get("confidence", 0.9),
                            "source": "llm_fanout",
                        }

                        cmd, issues = builder.build(
                            nlu_like,
                            source="llm_fanout",
                            context_logger=ctx_logger,
                            raw_text=raw,
                            contacts_registry=resolver,
                        )

                        if issues:
                            print(f"⚠️ Skipping {contact}: {issues}")
                            continue

                        res = dispatcher.execute(cmd)
                        print("Result:", res)

                        if res.success:
                            ctx_logger.update_from_command(cmd)

                    continue  # 🔴 CRITICAL: prevents falling into single-command path


            cmd_bridge = map_nlu_to_command({
                "intent": nlu_res.get("intent"),
                "slots": nlu_res.get("entities") or {},
                "confidence": nlu_res.get("confidence", 0.0),
                "meta": {"source": nlu_res.get("source")}
            }, source="voice")
            # Build & validate using CommandBuilder. Be tolerant of different builder signatures:
            built_kwargs = {
                "nlu_result": {
                    "intent": cmd_bridge.intent,
                    "entities": cmd_bridge.entities,
                    "confidence": cmd_bridge.confidence,
                    "source": cmd_bridge.source
                },
                "source": cmd_bridge.source,
                "context_logger": ctx_logger,
            }

            # The official builder.build signature may accept `raw_text` and `contacts_registry`.
            # Try to pass them; if builder doesn't accept them, fall back gracefully.
            try:
                cmd_validated, issues = builder.build(
                    built_kwargs["nlu_result"],
                    source=built_kwargs["source"],
                    context_logger=built_kwargs["context_logger"],
                    raw_text=raw,
                    contacts_registry=resolver
                )
            except TypeError:
                # try without contacts_registry and raw_text
                try:
                    cmd_validated, issues = builder.build(
                        built_kwargs["nlu_result"],
                        source=built_kwargs["source"],
                        context_logger=built_kwargs["context_logger"],
                    )
                except TypeError:
                    # older builder that expects the nlu_result as simple dict positional - try minimal call
                    cmd_validated, issues = builder.build({
                        "intent": cmd_bridge.intent,
                        "entities": cmd_bridge.entities,
                        "confidence": cmd_bridge.confidence,
                        "source": cmd_bridge.source
                    }, source=cmd_bridge.source, context_logger=ctx_logger)

            # Normalize return shape if builder returns 3-tuple by mistake
            if isinstance(cmd_validated, tuple) and len(cmd_validated) == 3:
                # older accidental tuple form (cmd, issues, something)
                cmd_validated, issues = cmd_validated[0], cmd_validated[1]

            if issues:
                print("Builder issues:", issues)
                # If missing required entity(s) — ask targeted question(s).
                missing_reqs = [i.split(":",1)[1] for i in issues if i.startswith("missing_required_entity")]
                if missing_reqs:
                    # ask first missing field explicitly (Layer-3)
                    field = missing_reqs[0]
                    q_map = {"contact":"Who should I send the message to?","text":"What should the message say?"}
                    print("🤖 I need clarification:")
                    print(q_map.get(field, "Can you clarify?"))
                    continue


                # handle ambiguous contact interactively using resolver
                if "ambiguous_contact" in issues or any(i.startswith("missing_required_entity:contact") for i in issues):
                    # try to propose candidates
                    contact_query = cmd_bridge.entities.get("contact") or raw
                    cands = resolver.candidates(contact_query, n=6, cutoff=0.30)
                    if cands:
                        if len(cands) == 1:
                            sel = cands[0][0]
                            print(f"Auto-selected contact: {sel}")
                        else:
                            print("I wasn't sure which contact you meant. Please type the contact's full name (or 'cancel'):")
                            for i, (name, score) in enumerate(cands, start=1):
                                print(f"  {i}. {name}  (score={score:.2f})")
                            choice = input("> ").strip()
                            if choice.lower() in ("cancel", "c"):
                                print("Cancelled.")
                                continue
                            if choice.isdigit():
                                idx = int(choice) - 1
                                sel = cands[idx][0] if 0 <= idx < len(cands) else None
                            else:
                                sel = choice

                        if choice.lower() in ("cancel", "c"):
                            print("Cancelled.")
                            continue
                        sel = None
                        if choice.isdigit():
                            idx = int(choice) - 1
                            if 0 <= idx < len(cands):
                                sel = cands[idx][0]
                        else:
                            sel = choice
                        if sel:
                            # patch cmd_bridge and rebuild
                            cmd_bridge.entities["contact"] = sel
                            try:
                                cmd_validated, issues = builder.build({
                                    "intent": cmd_bridge.intent,
                                    "entities": cmd_bridge.entities,
                                    "confidence": cmd_bridge.confidence,
                                    "source": cmd_bridge.source
                                }, source=cmd_bridge.source, context_logger=ctx_logger, raw_text=raw, contacts_registry=resolver)
                            except TypeError:
                                cmd_validated, issues = builder.build({
                                    "intent": cmd_bridge.intent,
                                    "entities": cmd_bridge.entities,
                                    "confidence": cmd_bridge.confidence,
                                    "source": cmd_bridge.source
                                }, source=cmd_bridge.source, context_logger=ctx_logger)
                            if issues:
                                print("Builder issues after clarification:", issues)
                                if cmd_validated is None:
                                    continue
                        else:
                            print("No valid selection. Skipping.")
                            continue
                    else:
                        # no candidates -> inform user and skip
                        print("No matching contacts found; please add contact to data/contacts.json or specify phone number.")
                        continue

                # other issues: prompt for clarification or skip for demo
                if cmd_validated is None:
                    continue

            # If we reached here, we have a validated Command
            print("Command:", cmd_validated)

            # Execute the command through dispatcher
            try:
                result = dispatcher.execute(cmd_validated)
            except Exception as e:
                print("Dispatch error:", e)
                continue

            print("Result:", result)

            # Update context logger if success
            if result and getattr(result, "success", False):
                try:
                    ctx_logger.update_from_command(cmd_validated)
                except Exception:
                    pass
                
                # Persist workflow if store is available (single command = single-step workflow)
                if workflow_store:
                    try:
                        wf_id = workflow_store.create_workflow(raw, [cmd_validated])
                        workflow_store.mark_workflow_state(wf_id, "completed")
                        log.debug("Single-command workflow persisted: %s", wf_id)
                    except Exception as e:
                        log.warning("Failed to persist workflow: %s", e)

    finally:
        # graceful cleanup for skills that expose _cleanup (playwright contexts etc)
        print("\nShutting down: cleaning up skills...")
        try:
            for s in list(registry._skills):
                if hasattr(s, "_cleanup"):
                    try:
                        s._cleanup()
                    except Exception:
                        pass
        except Exception:
            pass
        
        # Close workflow store if it exists
        if workflow_store:
            try:
                workflow_store.close()
                print("✓ Workflow store closed")
            except Exception:
                pass
        
        print("Goodbye.")


if __name__ == "__main__":
    main()
