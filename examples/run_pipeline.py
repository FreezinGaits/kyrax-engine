"""
examples/run_pipeline.py

Full example pipeline integrating:
 - NLUEngine (rule/keyword-based)
 - intent_mapper -> CommandBridge
 - CommandBuilder (with optional contacts resolver + raw_text)
 - ContactResolver (canonicalization + fuzzy lookup)
 - AIReasoner (LLM adapter optional via OPENAI_API_KEY env var)
 - Dispatcher -> SkillRegistry -> Playwright-backed WhatsAppSkill

Notes:
 - Ensure data/contacts.json exists and contains your contacts.
 - If you want LLM-backed reasoning, set OPENAI_API_KEY in env (optional).
 - This script is defensive: it works even if some optional pieces
   (OpenAI, builder contacts arg) are not installed/updated.
"""

import os
import time
import logging
import json
from typing import List

# core pipeline pieces
# use Gemini-backed LLM NLU
from kyrax_core.llm.gemini_client import GeminiClient
from kyrax_core.nlu.llm_nlu import LLMNLU
from kyrax_core.intent_mapper import map_nlu_to_command
from kyrax_core.command_builder import CommandBuilder
from kyrax_core.context_logger import ContextLogger
from kyrax_core.skill_registry import SkillRegistry
from kyrax_core.dispatcher import Dispatcher
from kyrax_core.command import Command
from kyrax_core.ai_reasoner import AIReasoner
# utils we added
from kyrax_core.contact_resolver import ContactResolver
from kyrax_core.ai_reasoner import AIReasoner

# skills
from skills.whatsapp_skill import WhatsAppSkill

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("run_pipeline")


# -------------------------
# Optional OpenAI adapter
# -------------------------
def get_openai_llm_callable():
    """
    Return a callable llm(prompt, max_tokens) -> str if openai is configured.
    Returns None if openai is not available or API key not set.
    """
    try:
        import openai
    except Exception:
        return None

    api_key = os.environ.get("OPENAI_API_KEY") or openai.api_key
    if not api_key:
        return None
    openai.api_key = api_key

    def llm(prompt: str, max_tokens: int = 512) -> str:
        # Use Chat Completions (gpt-3.5/4 whatever is available)
        try:
            resp = openai.ChatCompletion.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return resp.choices[0].message.content
        except Exception as e:
            raise

    return llm


# -------------------------
# Helper clause splitter
# -------------------------

def looks_like_direct_send(raw: str) -> bool:
    """
    Return True only for clear imperative send commands.
    """
    raw = raw.lower().strip()
    return any(raw.startswith(v) for v in (
        "send ",
        "text ",
        "message ",
        "whatsapp ",
        "send a message",
        "send hi",
        "send hey",
    ))
def resolve_contact_reference(contact: str, ctx_logger):
    """
    Resolve references like 'previous contact', 'last contact'.
    """
    if not contact:
        return contact

    c = contact.lower().strip()
    if c in ("previous contact", "last contact", "previous one", "last one"):
        if ctx_logger:
            last = ctx_logger.get("last_contact")
            if last:
                return last
    return contact

def split_clauses(raw: str) -> List[str]:
    import re
    parts = re.split(r'\b(?:and then|then|, then|,|;|\band\b|\bthen\b)\b', raw, flags=re.I)
    return [p.strip() for p in parts if p.strip()]

import re
import re

def extract_send_commands(raw: str):
    """
    Conservative extractor: returns list of dicts {contact, text}
    Accepts many spoken forms, including clauses that start with "to X saying Y".
    """
    out = []
    if not raw or not raw.strip():
        return out

    s = raw.strip()

    # split into clauses while keeping short pieces (covers ",", " and ", " then ")
    clauses = re.split(r',\s*|\s+\band\b\s+|\s+\bthen\b\s+', s, flags=re.I)
    for c in clauses:
        c = c.strip()
        if not c:
            continue

        # Pattern 1: forms like:
        #  "send a message to Akshat saying hi"
        #  "to Gautam saying hey"
        m = re.search(
            r'^(?:send\s+(?:a\s+message\s+)?)?(?:to\s+)?(?P<contact>[^,;]+?)\s+(?:saying|says)\s+["\']?(?P<text>[^,"\';]+?)["\']?\s*$',
            c,
            flags=re.I,
        )
        if m:
            contact = m.group("contact").strip()
            text = m.group("text").strip()
            if contact and text:
                out.append({"contact": contact, "text": text})
                continue

        # Pattern 2: "text Akshat saying hi" or "text Akshat, hi"
        m = re.search(r'^(?:text|message)\s+(?P<contact>[^,;]+?)\s+(?:saying|says)\s+["\']?(?P<text>[^,"\';]+?)["\']?$', c, flags=re.I)
        if m:
            out.append({"contact": m.group("contact").strip(), "text": m.group("text").strip()})
            continue

        # Pattern 3: "send hi to Akshat"
        m = re.search(r'^(?:send\s+)?(?P<text>[^,;]+?)\s+to\s+(?P<contact>[^,;]+)$', c, flags=re.I)
        if m:
            out.append({"contact": m.group("contact").strip(), "text": m.group("text").strip()})
            continue

        # Pattern 4: shorthand "send Akshat hi" or "send Akshat, hi"
        # m = re.search(r'^(?:send\s+)?(?P<contact>[A-Za-z0-9 _\-\+]+?)\s+[,\-]?\s*(?P<text>.+)$', c, flags=re.I)
        if m:
            contact = m.group("contact").strip()
            text = m.group("text").strip()
            # avoid spurious matches like "send a package" -> require short contact token
            if len(contact.split()) <= 4 and text:
                out.append({"contact": contact, "text": text})
                continue

    return out


# -------------------------
# Main CLI pipeline
# -------------------------
def main():
    print("Starting KYRAX pipeline (examples/run_pipeline.py)")



    # instantiate Gemini adapter (optionally pass model name)
    gemini = GeminiClient()  # or "text-bison-001" if your project uses that model id
    nlu = LLMNLU(gemini_client=gemini)

    builder = CommandBuilder()
    ctx_logger = ContextLogger(max_entries=200, ttl_seconds=3600)
    registry = SkillRegistry()

    # Contact resolver: use positional arg for compatibility with different signatures
    # This avoids TypeError: ContactResolver.__init__() got an unexpected keyword argument 'contacts_path'
    resolver = ContactResolver("data/contacts.json")

    # AI reasoner with optional OpenAI adapter
    # llm_callable = get_openai_llm_callable()
    # provide a simple callable: llm_callable(prompt, max_tokens)

    start = time.time()

    llm_callable = lambda prompt, max_tokens=512: gemini.complete(prompt, max_tokens=max_tokens, temperature=0.0)
    reasoner = AIReasoner(llm=llm_callable)
    # keep a flag/timer to avoid repeatedly hitting Gemini when quota is exhausted
    llm_available = True
    llm_disabled_until = 0.0  # unix timestamp until which LLM use is disabled
    LLM_DISABLE_DEFAULT = 60  # seconds to disable LLM after RESOURCE_EXHAUSTED (tunable)
    log.info("Gemini took %.2fs", time.time() - start)

    # Register skills (Playwright WhatsApp skill)
    wa_profile = r"C:\Users\HP\kyrax_wa_profile"  # change to your path
    wa_skill = WhatsAppSkill(profile_dir=wa_profile, headless=False, close_on_finish=False, browser_type="chromium")
    registry.register(wa_skill)
    # Register other skills if available (OS, IoT, File, etc.)
    # e.g. registry.register(OSSkill(...))

    dispatcher = Dispatcher(registry=registry)

    print("KYRAX CLI (type 'exit' to quit). Example: send a message to Akshat: 'send a message to Akshat saying hi'")

    try:
        while True:
            try:
                raw = input("\n> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break
            if not raw:
                continue
            if raw.lower() in ("exit", "quit"):
                break

            # ---- deterministic multi-send handler (MUST RUN FIRST) ----
            multi_cmds = extract_send_commands(raw)
            if multi_cmds and looks_like_direct_send(raw): # Handle even single commands (len >=1) to bypass Gemini
                print(f"Detected {len(multi_cmds)} send-message task(s) (local parser). Executing sequentially.")
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
                        cmd_validated, issues = builder.build(
                            nlu_like,
                            source="local_parser",
                            context_logger=ctx_logger,
                            raw_text=raw,
                            contacts_registry=resolver,
                        )
                    except TypeError:
                        cmd_validated, issues = builder.build(
                            nlu_like,
                            source="local_parser",
                            context_logger=ctx_logger,
                        )
                    if issues:
                        print("Builder issues:", issues)
                        # auto-resolve single candidate
                        if "ambiguous_contact" in issues:
                            cands = resolver.candidates(step["contact"], n=5, cutoff=0.35)
                            if len(cands) == 1:
                                cmd_validated.entities["contact"] = cands[0][0]
                            else:
                                print("Cannot resolve contact:", step["contact"])
                                continue
                    if cmd_validated:
                        print("Executing:", cmd_validated)
                        res = dispatcher.execute(cmd_validated)
                        print("Result:", res)
                        if res.success:
                            ctx_logger.update_from_command(cmd_validated)
                continue  # 🚨 IMPORTANT: do NOT fall through to AIReasoner or NLU/Gemini

            # If user input looks like a multi-step compound, prefer AI Reasoner to propose a plan
            clauses = split_clauses(raw)
            is_compound = len(clauses) > 1

            # If we have an LLM and the user wrote a compound sentence, ask reasoner for proposals
            if is_compound and reasoner and llm_callable:
                try:
                    proposals = reasoner.propose_and_validate_plan(raw, context=ctx_logger.get_all() if hasattr(ctx_logger, "get_all") else {}, command_builder=builder, max_candidates=1)
                except Exception:
                    proposals = []

                if proposals:
                    # proposals is list of tuples (PlanProposal, [(Command|None, issues), ...])
                    plan, validated = proposals[0]
                    print(f"AI proposed plan: {plan.explanation} (score={plan.score:.2f})")
                    for idx, (cmd_obj, issues) in enumerate(validated, start=1):
                        print(f" Step {idx}: {cmd_obj}  issues={issues}")
                        if issues:
                            print("  -> Issues found; will skip execution of this step unless clarified.")
                        else:
                            # Execute validated command
                            print(f" Executing: {cmd_obj}")
                            res = dispatcher.execute(cmd_obj)
                            print("  Result:", res)
                            if res.success:
                                try:
                                    ctx_logger.update_from_command(cmd_obj)
                                except Exception:
                                    pass
                    # After handling the plan, go to next user input
                    continue

            # --- Single-clause / fallback path: NLU -> map -> build -> dispatch
            # Call LLM-backed NLU only when llm_available and not temporarily disabled
            if llm_available and time.time() >= llm_disabled_until:
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
                        # Try to fallback to non-LLM parsing (we already run extract_send_commands above, so just continue loop)
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
                print("⚠️ AI temporarily unavailable. Please use simple commands (e.g., 'send hi to Alice').")
                continue


            # Use the bridge to get a Command-like object
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

    finally:
        # graceful cleanup for skills that expose _cleanup (playwright contexts etc)
        print("Shutting down: cleaning up skills...")
        try:
            for s in list(registry._skills):
                if hasattr(s, "_cleanup"):
                    try:
                        s._cleanup()
                    except Exception:
                        pass
        except Exception:
            pass
        print("Goodbye.")


if __name__ == "__main__":
    main()
