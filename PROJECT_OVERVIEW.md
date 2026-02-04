# KYRAX-Engine — Project Overview

This document describes every file, the pipeline flow, which parts are used vs unused, what works and what doesn’t, the tech stack per area, current capabilities, and future improvements.

---

## 1. What the project is

**KYRAX Engine** is an AI-first system that reasons, plans, and executes tasks across OS, apps, and IoT. Voice, text, and vision are input modalities; the core is intent → plan → command → skill execution.

- **Core flow:** User input (text/voice) → NLU (intent + entities) → optional AI reasoner/planner → CommandBuilder → Dispatcher → SkillRegistry → Skill.execute() → result.
- **Main entry:** The only “full” pipeline wired end-to-end is **`examples/run_pipeline.py`**. It uses Gemini for NLU, CommandBuilder + ContactResolver, AIReasoner for compound goals, and a Playwright-based WhatsApp skill.

---

## 2. Role of each file (by folder)

### Root / config

| File               | Role                                                                                                                                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `README.md`        | Short project description (AI-first, reason/plan/execute).                                                                                                                                                                     |
| `pyproject.toml`   | Python ≥3.13, deps: fastapi, uvicorn, pydantic, openai, openai-whisper, selenium, sounddevice, soundfile, spacy, webdriver-manager. **Note:** No `google-genai` here; Gemini is used in code but must be installed separately. |
| `requirements.txt` | Lighter list: fastapi, uvicorn, pydantic, openai-whisper, sounddevice, soundfile, ffmpeg (system).                                                                                                                             |
| `uv.lock`          | Lockfile for uv (includes spacy, playwright via transitive deps, etc.).                                                                                                                                                        |
| `.gitignore`       | Standard ignores.                                                                                                                                                                                                              |
| `.python-version`  | Python version for env.                                                                                                                                                                                                        |

### `kyrax_core/` — core engine

| File                  | Role                                                                                                                                                                                                                                                                                                                                                           | Tech / libs                                              |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `__init__.py`         | Empty; package marker.                                                                                                                                                                                                                                                                                                                                         | —                                                        |
| `command.py`          | **Command** dataclass: intent, domain, entities, confidence, source. `is_valid()`, `to_json()` / `from_json()`, `to_dict()`. Central payload for the whole pipeline.                                                                                                                                                                                           | stdlib (dataclasses, json)                               |
| `command_builder.py`  | **CommandBuilder**: turns NLU dict → validated **Command**. Schema per intent (required/optional entities, normalizers). Optional `contacts_registry` for contact resolution; ambiguity detection.                                                                                                                                                             | stdlib                                                   |
| `intent_mapper.py`    | **map_nlu_to_command()**: NLU payload (intent, slots/entities, confidence) → **Command**. Domain heuristics, **normalize_entities()** (slot → entity name).                                                                                                                                                                                                    | stdlib                                                   |
| `dispatcher.py`       | **Dispatcher**: takes **Command**, uses **SkillRegistry.find_handler()**, runs `handler.execute(command, context)`, returns **SkillResult**. Confidence gating, optional timeout. **API: `execute()` only (no `dispatch()`).**                                                                                                                                 | stdlib                                                   |
| `skill_base.py`       | **Skill** ABC: `can_handle(command)`, `execute(command, context)` → **SkillResult**. **SkillResult**: success, message, data, code.                                                                                                                                                                                                                            | stdlib                                                   |
| `skill_registry.py`   | **SkillRegistry**: register/unregister skills, **find_handler(command)** (first skill that can_handle).                                                                                                                                                                                                                                                        | stdlib                                                   |
| `planner.py`          | **TaskPlanner**: goal string → list of **Command**. Template matching (e.g. prepare_presentation, default_meeting_setup) + heuristic decomposition. Placeholder expansion from context. **execute_plan()** calls `dispatcher.dispatch(cmd)` (interface mismatch with real Dispatcher).                                                                         | stdlib, re                                               |
| `planner_pipeline.py` | **plan_validate_and_dispatch()**: plan → validate with CommandBuilder → dispatch. Uses **ChainExecutor.execute_chain()** and then a loop that calls **dispatcher.dispatch()**. Expects dispatcher to have **dispatch()** and return dict-like; real **Dispatcher** has **execute()** and returns **SkillResult** → **not compatible** with current Dispatcher. | chain_executor, planner, command_builder, context_logger |
| `chain_executor.py`   | **ChainExecutor**: runs a list of **Command** in order via **dispatcher.dispatch(cmd)**. Resolves placeholders like `{{ last.file_path }}`, `{{ steps.0.x }}`, `{{ global.x }}` from previous step results. Returns (results_list, issues_list). Expects **dispatch()** and dict-like results.                                                                 | stdlib, re                                               |
| `ai_reasoner.py`      | **AIReasoner**: optional LLM callable; **suggest_plans()** (LLM or deterministic), **resolve_ambiguity()**, **propose_and_validate_plan()** (plan → CommandBuilder validation). **ProposedCommand** / **PlanProposal** dataclasses.                                                                                                                            | stdlib, json, re, uuid                                   |
| `context_logger.py`   | **ContextLogger**: short-term memory (deque, TTL). **update_from_command()**, **get_most_recent(key)**, **resolve_pronoun()**, **fill_missing_entities()**, **snapshot()**. No **get_all()**; run_pipeline uses `get_all()` only behind hasattr so it falls back to `{}`.                                                                                      | stdlib, threading, re                                    |
| `contact_resolver.py` | **ContactResolver**: loads contacts from JSON; **find_best(query)**, **candidates(query, n, cutoff)**. Fuzzy/substring/phone matching. Used by CommandBuilder.                                                                                                                                                                                                 | stdlib, json, difflib, re                                |
| `guards.py`           | **GuardManager**: rate limit, role ACL, destructive/sensitive intent checks, path whitelist. **validate()** → **GuardResult** (allowed/blocked/require_confirmation). **guard_and_dispatch()** helper. Not wired into run_pipeline.                                                                                                                            | stdlib, threading, re                                    |
| `workflow_manager.py` | **WorkflowStore** (SQLite): workflows + steps (Command JSON, status, result). **create_workflow()**, **get_next_pending_step()**, **mark*step*\*()**, **explain_workflow()**. Used only in demos with a **DummyDispatcher** that has **dispatch()**.                                                                                                           | stdlib, sqlite3, json, uuid                              |
| `audit.py`            | Append-only **audit_record()** to file (e.g. guard decisions, executed commands). Not called from main pipeline.                                                                                                                                                                                                                                               | stdlib, json                                             |
| `llm_adapters.py`     | **openai_llm_callable(api_key)** and **deterministic_llm_stub()** for AIReasoner. Optional; run_pipeline uses Gemini directly.                                                                                                                                                                                                                                 | openai (optional), json                                  |

### `kyrax_core/nlu/`

| File            | Role                                                                                                                                                                                                                      | Tech / libs                |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| `nlu_engine.py` | **NLUEngine**: rule/keyword NLU. spaCy Matcher + keyword classifier. **analyze(text)** → {intent, entities, confidence, source}. Optional **map_to_command()**. **Not used by run_pipeline** (run_pipeline uses LLM NLU). | spacy (optional), re       |
| `llm_nlu.py`    | **LLMNLU**: Gemini-backed. **analyze(text)** → prompt Gemini, parse JSON → {intent, entities, confidence, source}. **Used by run_pipeline.**                                                                              | json, re, **GeminiClient** |

### `kyrax_core/llm/`

| File               | Role                                                                                                                                                                           | Tech / libs                                             |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| `gemini_client.py` | **GeminiClient**: `google.genai` client, model fallback list, **complete(prompt, max_tokens, temperature)**. Requires **GEMINI_API_KEY**. **Used by run_pipeline and LLMNLU.** | **google.genai** (not in pyproject; install separately) |

### `kyrax_core/adapters/`

| File               | Role                                                                                                                      | Tech / libs                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `base.py`          | **InputAdapter** ABC, **AdapterOutput** dataclass (text, source, meta, timestamp). **listen()** → AdapterOutput.          | stdlib                                            |
| `text_adapter.py`  | **CLITextAdapter**: `input(prompt)` → AdapterOutput. Not used in run_pipeline (run_pipeline uses raw `input()`).          | stdlib                                            |
| `voice_adapter.py` | **WhisperVoiceAdapter**: transcribe file or mic → AdapterOutput. openai-whisper, optional sounddevice/soundfile.          | openai-whisper, sounddevice, soundfile (optional) |
| `api_adapter.py`   | FastAPI app: **POST /text**, **POST /transcribe** (upload audio). Wraps AdapterOutput. Not part of the main CLI pipeline. | fastapi, pydantic, WhisperVoiceAdapter            |

### `skills/`

| File                | Role                                                                                                                                                                                                                                                                                             | Tech / libs                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `whatsapp_skill.py` | **WhatsAppSkill** (Playwright): profile_dir, headless, browser. **can_handle**: application + send_message. **execute()** runs in ThreadPoolExecutor, opens WhatsApp Web, search contact, send text. Large commented block is old Selenium version. **Used by run_pipeline** (with profile_dir). | playwright (sync_api), ThreadPoolExecutor; contacts from data/contacts.json |
| `os_skill.py`       | **OSSkill**: open_app / launch / close_app, domain "os". Resolves app via shutil.which, subprocess. **dry_run** option. **Not registered in run_pipeline** (only WhatsApp is).                                                                                                                   | stdlib, platform, shutil, subprocess                                        |
| `iot_skill.py`      | **IoTSkill**: turn_on/turn_off/set/toggle, domain "iot". Optional MQTT client; else simulated. **Not registered in run_pipeline.**                                                                                                                                                               | stdlib                                                                      |

### `server/`

| File                | Role                                                                                                                                             | Tech / libs |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| `intent_handler.py` | Commented pseudo-code: **handle_goal_intent(goal_text)** calling **plan_validate_and_dispatch** with a “RealDispatcher”. **Not runnable as-is.** | —           |

### `data/`

| File            | Role                                                                                                                          |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `contacts.json` | Contact list for ContactResolver and WhatsApp skill (name, whatsapp_name, phone). **Used by run_pipeline and WhatsAppSkill.** |

### `examples/`

| File                            | Role                                                                                                                                                                                                                                            | In main pipeline?            |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| `run_pipeline.py`               | **Main pipeline**: Gemini + LLMNLU, CommandBuilder, ContactResolver, ContextLogger, AIReasoner, Dispatcher, WhatsAppSkill. Local multi-send parser, compound → reasoner, single → NLU → build → dispatch. **Only entry that wires everything.** | **Yes** (it is the pipeline) |
| `run_pipeline9.py`              | Variant of run_pipeline (same idea, small differences). Not the primary entry.                                                                                                                                                                  | No (alternate)               |
| `run_dispatcher.py`             | Minimal demo: manual NLU dicts → map_nlu_to_command → Dispatcher.execute() with WhatsApp, OS, IoT skills. **Dispatcher has execute(); works.**                                                                                                  | No (demo)                    |
| `demo_planner_pipeline.py`      | **plan_validate_and_dispatch** with TaskPlanner + DummyDispatcher(**dispatch()**). Shows planner pipeline with a fake dispatcher.                                                                                                               | No (demo)                    |
| `demo_workflow_manager.py`      | WorkflowStore + DummyDispatcher(**dispatch()**), step-by-step execution.                                                                                                                                                                        | No (demo)                    |
| `demo_planner.py`               | TaskPlanner.plan() only.                                                                                                                                                                                                                        | No (demo)                    |
| `demo_reasoner.py`              | AIReasoner suggest_plans / propose_and_validate_plan.                                                                                                                                                                                           | No (demo)                    |
| `demo_context_flow.py`          | ContextLogger fill_missing_entities / resolve.                                                                                                                                                                                                  | No (demo)                    |
| `demo_guardrails.py`            | GuardManager validate / guard_and_dispatch.                                                                                                                                                                                                     | No (demo)                    |
| `demo_skill_chaining.py`        | ChainExecutor with placeholder resolution and a dummy dispatcher.                                                                                                                                                                               | No (demo)                    |
| `nlu_demo.py`                   | NLUEngine or NLU usage.                                                                                                                                                                                                                         | No (demo)                    |
| `adapter_demo.py`               | Input adapters (text/voice).                                                                                                                                                                                                                    | No (demo)                    |
| `test_command_builder.py`       | CommandBuilder tests.                                                                                                                                                                                                                           | No (test)                    |
| `test_command.py`               | Command serialization.                                                                                                                                                                                                                          | No (test)                    |
| `test_context_logger_simple.py` | ContextLogger.                                                                                                                                                                                                                                  | No (test)                    |
| `test_skills.py`                | SkillRegistry.find_handler + skill.execute.                                                                                                                                                                                                     | No (test)                    |
| `test_whatsapp_send.py`         | Direct WhatsAppSkill.execute.                                                                                                                                                                                                                   | No (test)                    |

### Other

| File                             | Role                        |
| -------------------------------- | --------------------------- |
| `test/test.py`, `test/audio.m4a` | Ad-hoc test / sample audio. |
| `.vscode/mcp.json`               | MCP config for editor.      |

---

## 3. How the pipeline runs (and what’s used)

- **Only full pipeline:** `examples/run_pipeline.py`.
- **Folders used in that pipeline:**
  - **kyrax_core:** command, command_builder, intent_mapper, context_logger, contact_resolver, skill_registry, dispatcher, skill_base, ai_reasoner, nlu/llm_nlu, llm/gemini_client.
  - **skills:** whatsapp_skill only.
  - **data:** contacts.json.

Flow in `run_pipeline.py`:

1. **Input:** `input("> ")` (no adapters).
2. **Multi-send fast path:** If input looks like “send … to X saying Y”, **extract_send_commands()** + **resolve_contact_reference()** → nlu-like dict → **CommandBuilder.build()** (with ContactResolver) → **Dispatcher.execute()** → **ContextLogger.update_from_command()**. No Gemini.
3. **Compound sentence:** If multiple clauses and AIReasoner available, **reasoner.propose_and_validate_plan()** → validated commands → **Dispatcher.execute()** for each → context update.
4. **Single-clause / fallback:** **LLMNLU.analyze()** (Gemini) → **map_nlu_to_command()** → **CommandBuilder.build()** (with ContactResolver, ContextLogger) → optional contact disambiguation → **Dispatcher.execute()** → context update.

**Not used in this pipeline:**

- **kyrax_core:** planner_pipeline, planner, chain_executor, workflow_manager, guards, audit, nlu_engine, adapters (text/voice/api), llm_adapters.
- **skills:** os_skill, iot_skill.
- **server:** intent_handler (stub only).

---

## 4. What doesn’t work (and why)

1. **Planner pipeline + real Dispatcher**

   - **planner_pipeline.plan_validate_and_dispatch()** and **ChainExecutor** call **dispatcher.dispatch(cmd)** and expect a dict-like return.
   - **Dispatcher** only has **execute(cmd)** and returns **SkillResult**.
   - So using the real **Dispatcher** inside **plan_validate_and_dispatch** or **ChainExecutor** would raise **AttributeError** (no `dispatch`). Demos work because they use a **DummyDispatcher** with **dispatch()**.

2. **Duplicate execution in planner_pipeline**

   - It first runs **ChainExecutor.execute_chain(planned_commands, dispatcher)** (which would call **dispatch()**), then loops over the same commands, validates, and calls **dispatcher.dispatch()** again. So even after fixing the API, logic would run commands twice.

3. **ContextLogger.get_all()**

   - **run_pipeline** uses `ctx_logger.get_all()` behind `hasattr`, so it falls back to `{}` and doesn’t crash. **ContextLogger** only has **snapshot()** / **get_most_recent()**, not **get_all()**.

4. **Pattern 4 in extract_send_commands (run_pipeline)**

   - The regex for “send Akshat hi” is commented out; the following `if m:` uses the previous pattern’s `m`. So that shorthand form is never matched.

5. **run_dispatcher + WhatsAppSkill**

   - **run_dispatcher** registers **WhatsAppSkill()** with no **profile_dir**. For real WhatsApp Web you need a profile_dir; otherwise the skill may fail or open a new session every time.

6. **Gemini dependency**

   - **gemini_client** uses `google.genai`. It’s not in **pyproject.toml**; must be installed separately (e.g. `google-genai`) or run_pipeline fails at import/use.

7. **Server intent_handler**

   - **server/intent_handler.py** is commented pseudo-code; not a runnable server.

8. **Guards / Audit**
   - **GuardManager** and **audit_record()** are never called from the main pipeline, so safety/audit are not applied in production path.

---

## 5. Tech stack per area (and why)

- **NLU:** Gemini (LLM) in run_pipeline for flexibility and quality; spaCy in nlu_engine for optional rule-based, low-latency path.
- **LLM:** google.genai for Gemini (NLU + reasoner); openai in llm_adapters optional for alternative reasoner.
- **Voice:** openai-whisper + sounddevice/soundfile in voice_adapter; not in main CLI.
- **HTTP:** FastAPI + uvicorn in api_adapter for future text/transcribe endpoints.
- **WhatsApp:** Playwright (sync) for browser automation; Selenium code in whatsapp_skill is commented legacy.
- **Validation:** Pydantic in api_adapter; Command is a dataclass.
- **Data:** contacts in JSON; workflow state in SQLite (workflow_manager).
- **Concurrency:** ThreadPoolExecutor in WhatsApp skill to isolate Playwright from asyncio.

Other libs (spacy, selenium, webdriver-manager) are in pyproject for nlu_engine and the old Selenium path; the active pipeline doesn’t use them.

---

## 6. What the project can do today

- **Text CLI:** Run `run_pipeline.py`, type natural language.
- **Send WhatsApp messages:** “Send to Akshat saying hi”, “send hi to Gautam” (with contacts in data/contacts.json and a configured Chrome profile).
- **Multi-send:** “Send to A saying X and to B saying Y” via local parser (no Gemini).
- **Compound goals:** Multi-step plans via AIReasoner (Gemini) then execute each step (e.g. two messages).
- **Contact resolution:** Fuzzy match and “previous/last contact” via ContextLogger + ContactResolver.
- **Single intent:** One sentence → Gemini NLU → build → dispatch (e.g. one WhatsApp send).
- **Fallback:** If Gemini is rate-limited, pipeline falls back to a message asking for simple commands.

---

## 7. What it doesn’t do (yet)

- **Voice in pipeline:** Voice adapter exists but isn’t wired; main pipeline is text-only.
- **OS / IoT in main pipeline:** OS and IoT skills exist but aren’t registered in run_pipeline.
- **Planner + ChainExecutor in production:** Template planner and chain executor aren’t used with the real Dispatcher (API mismatch and duplicate execution).
- **Workflow persistence:** WorkflowStore is only used in demos with a dummy dispatcher.
- **Guards and audit:** No rate limit, ACL, or audit in the main path.
- **HTTP API:** api_adapter exists but isn’t the entry point for the full pipeline.
- **Server intent handler:** No real server implementing the full pipeline.

---

## 8. How to improve in the future

1. **Unify dispatcher API**

   - Add **dispatch(cmd)** on **Dispatcher** that calls **execute(cmd)** and returns a dict (e.g. `{"success": r.success, "message": r.message, **r.data}`) so **planner_pipeline** and **ChainExecutor** can use the real Dispatcher without changing their contracts.

2. **Fix planner_pipeline flow**

   - Either use only **ChainExecutor** (with placeholder resolution) and remove the duplicate validation/dispatch loop, or use only the validate-then-dispatch loop and drop the initial **execute_chain** call. Document which path is canonical.

3. **Add ContextLogger.get_all()**

   - Implement **get_all()** returning a flat dict of latest keys (e.g. last_contact, last_app) from the most recent records so reasoner/planner get a simple context dict.

4. **Fix extract_send_commands**

   - Uncomment and fix Pattern 4 (e.g. “send Akshat hi”) so that branch uses its own regex and doesn’t reuse `m` from Pattern 3.

5. **Put Gemini in pyproject**

   - Add `google-genai` (or the correct package name) to **pyproject.toml** so the main pipeline is installable in one step.

6. **Wire guards into pipeline**

   - Before **Dispatcher.execute()**, call **GuardManager.validate()** and respect **GuardResult** (block, require confirmation, or allow). Optionally call **audit_record()** for executed commands and guard decisions.

7. **Optional OS/IoT in run_pipeline**

   - Register **OSSkill** and **IoTSkill** when desired (e.g. via env or flag) so “open app” and “turn on light” work from the same CLI.

8. **Voice in pipeline**

   - In run_pipeline, optionally use **WhisperVoiceAdapter.listen(mode="mic")** or from file and feed **AdapterOutput.text** into the same NLU → build → dispatch flow.

9. **FastAPI server**

   - Implement **server/intent_handler** (or a new module) that runs the full pipeline (NLU → reasoner/planner → build → guard → dispatch) and expose **POST /goal** or **POST /text** using the same components as run_pipeline.

10. **Cleanup**

- Remove or clearly separate the large commented Selenium block in whatsapp_skill. Consider moving run_pipeline’s local send parsing into a small helper or kyrax_core so the example stays thin.

---

_Generated as PROJECT_OVERVIEW.md for the kyrax-engine repo._

Summary
What each part does
kyrax_core/ – Command model, CommandBuilder, intent_mapper, Dispatcher, SkillRegistry, TaskPlanner, AIReasoner, ContextLogger, ContactResolver, ChainExecutor, guards, workflow_manager, audit, NLU (rule + LLM), Gemini client, input adapters (text/voice/API).
skills/ – WhatsApp (Playwright, used in pipeline), OS (open app), IoT (turn on/off; both not in main pipeline).
examples/run_pipeline.py – The only full pipeline: Gemini NLU → CommandBuilder + ContactResolver → optional AIReasoner for compound goals → Dispatcher → WhatsAppSkill.
Pipeline flow (what’s actually used)
Input: input("> ") (no adapter).
Direct send: If it looks like “send … to X saying Y” → local parser → CommandBuilder (with ContactResolver) → Dispatcher.execute() → WhatsAppSkill.
Compound: If multiple clauses and AIReasoner is available → reasoner proposes plan → CommandBuilder validates → Dispatcher.execute() for each step.
Single clause: Otherwise → LLMNLU (Gemini) → map_nlu_to_command → CommandBuilder → Dispatcher.execute().
Used: kyrax_core (command, command_builder, intent_mapper, context_logger, contact_resolver, skill_registry, dispatcher, ai_reasoner, nlu/llm_nlu, llm/gemini_client), skills/whatsapp_skill.py, data/contacts.json.
Not used in this pipeline: planner_pipeline, planner, chain_executor, workflow_manager, guards, audit, nlu_engine, adapters, os_skill, iot_skill, server (stub only).
What’s broken or inconsistent
Dispatcher API – planner_pipeline and ChainExecutor call dispatcher.dispatch(cmd) and expect a dict; real Dispatcher only has execute(cmd) and returns SkillResult → AttributeError if you pass the real Dispatcher.
planner_pipeline – Runs ChainExecutor then does validate + dispatch again on the same commands (double execution even after fixing the API).
ContextLogger – No get_all(); run_pipeline uses it behind hasattr so it falls back to {}.
extract_send_commands – Pattern 4 (“send Akshat hi”) is commented out; the following if m: reuses Pattern 3’s m, so that form never matches.
Gemini – Used in code but google-genai is not in pyproject.toml; must be installed separately.
Guards / audit – Never called from the main pipeline.
Tech stack (per area)
NLU: Gemini (LLM) in pipeline; spaCy in nlu_engine (optional, not in pipeline).
LLM: google.genai (Gemini); optional OpenAI in llm_adapters.
WhatsApp: Playwright (sync); Selenium code in whatsapp_skill is commented.
Server/API: FastAPI in api_adapter; not wired to full pipeline.
Voice: openai-whisper + sounddevice/soundfile in voice_adapter; not in main CLI.
Current capabilities
Text CLI: “send to X saying Y”, multi-send (“to A saying X and to B saying Y”), compound goals via AIReasoner, contact resolution and “previous contact”, single intent via Gemini NLU, fallback when Gemini is rate-limited.
Not in the main pipeline yet
Voice input, OS/IoT skills, planner + ChainExecutor with real Dispatcher, workflow persistence, guards, audit, HTTP API for the full pipeline.
Suggested next steps (from the doc)
Add dispatch(cmd) on Dispatcher that wraps execute(cmd) and returns a dict so planner_pipeline and ChainExecutor can use it.
Fix planner_pipeline so it doesn’t run the same commands twice (either use ChainExecutor only or the validate+dispatch loop only).
Implement ContextLogger.get_all() and use it where run_pipeline expects it.
Fix Pattern 4 in extract_send_commands (uncomment and use correct regex).
Add google-genai to pyproject.toml.
Call GuardManager.validate() (and optionally audit_record()) before execution in the main path.
Optionally register OS/IoT skills, wire voice adapter, and implement a real FastAPI server that runs the full pipeline.
Full detail, file-by-file roles, and exact references are in PROJECT_OVERVIEW.md in the repo root.
