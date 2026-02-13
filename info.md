# KYRAX Engine - Project Information

## 1. Project Overview
**KYRAX Engine** is an AI-first operating system interface designed to reason, plan, and execute complex tasks across desktop applications, web services, and IoT devices.

Unlike traditional assistants that map rigid voice commands to specific actions, KYRAX uses a Flexible NLU -> Reasoning -> Execution pipeline. It treats user input (text, voice) as a goal to be interpreted, planned for, and executed using a registry of "Skills".

**Key Philosophy:**
*   **Intelligence Core:** The system reasons about the user's intent rather than just pattern matching.
*   **Modality Agnostic:** Voice and text are just input channels; the core logic is the same.
*   **Skill-Based:** Functionality is modular (WhatsApp, OS control, IoT).

## 2. Core Capabilities (What it CAN do)
*   **Natural Language Command Execution:** "Send a message to Akshat saying hi" -> Executes WhatsApp send.
*   **Compound Goal Planning:** "Send the report to Akshat and then open the presentation" -> Decomposes into multiple steps (Send WhatsApp -> Open App).
*   **Context Awareness:** Remembers recent interactions (e.g., "Send to *him*" resolves to the last contacted person).
*   **Contact Resolution:** Fuzzy text matching for names against a contact database (`data/contacts.json`).
*   **WhatsApp Automation:** Fully functional WhatsApp Web automation via Playwright (handles login checks, searching contacts, sending messages).
*   **OS Automation (Partial):** Can launch applications, control volume (`os_skill.py`).
*   **Input Flexibility:** Handles simple direct commands, multi-intent sentences, and vague goals requiring LLM reasoning.

## 3. Limitations & Status (What it CANNOT do yet)
*   **Voice Input:** The module (`voice_adapter.py`) exists but is **not wired** into the main `run_pipeline.py`. The system is currently Text-CLI only.
*   **Safety & Security:** Components for Policy (`policy_store.py`), Rate Limiting (`ratelimiter_redis.py`), and Confirmation (`confirmation_gate.py`) exist but are **not currently active** in the main execution pipeline.
*   **Server Mode:** The `server/` directory is currently empty. There is no active HTTP API for the engine; it runs as a local Python script.
*   **IoT Control:** `iot_skill.py` is implemented but uses simulated devices/MQTT and is largely for demonstration.
*   **Full OS Control:** Complex OS detailed actions (like "organize my files") are not yet implemented; supports basic app launch/volume control.

## 4. detailed File Structure & Descriptions

### Root Directory
| File | Description | Status |
| :--- | :--- | :--- |
| `PROJECT_OVERVIEW.md` | High-level architectural documentation and status report. | **Reference** |
| `IMPROVEMENTS_SUMMARY.md` | Log of recent refactors and fixes (e.g., Dispatcher API unification). | **Reference** |
| `README.md` | Brief introductory text. | **Reference** |
| `pyproject.toml` | Python project configuration and dependencies. | **Active** |
| `requirements.txt` | Alternative dependency list (lighter). | **Active** |
| `.env` | Environment variables (API keys, config flags). | **Config** |
| `.gitignore` | Git ignore rules. | **Config** |
| `kyrax_workflows.db` | SQLite database for persisting workflow states. | **Data** |
| `kyrax_audit.log` | Log file for audit records (when enabled). | **Log** |

### `kyrax_core/` (The Engine Heart)
Contains the core logic for NLU, reasoning, and execution.

| File | Description | Status |
| :--- | :--- | :--- |
| **`command.py`** | Defines the `Command` dataclass (intent, entities, domain), the central data structure. | **Core** |
| **`command_builder.py`** | Validates and normalizes commands (e.g., resolves "Chrome" to "Google Chrome"). | **Core** |
| **`dispatcher.py`** | Routes commands to the appropriate Skill. Has `execute()` (returns result) and `dispatch()` (returns dict). | **Core** |
| **`skill_registry.py`** | Manages available skills. Finds the right handler for a command. | **Core** |
| **`skill_base.py`** | Abstract Base Class for all skills (`can_handle`, `execute`). | **Interface** |
| **`ai_reasoner.py`** | Uses LLM to decompose complex goals into valid execution plans. | **Core** |
| **`context_logger.py`** | Short-term memory. Tracks usage context (last app, last contact) to resolve pronouns. | **Core** |
| **`contact_resolver.py`** | Fuzzy matcher for finding contacts in `contacts.json`. | **Core** |
| **`chain_executor.py`** | Executes a sequence of commands, passing data between steps (e.g. output of step 1 -> input of step 2). | **Core** |
| **`workflow_manager.py`** | Manages long-running workflows and persists them to SQLite. | **Active** |
| `intent_mapper.py` | Helper to map raw NLU output to strict Command objects. | **Active** |
| `config.py` | Central runtime config loader (environment variables). | **Active** |
| `contact_store.py` | Helper class to load/save `contacts.json`. | **Active** |
| `audit.py` | Helper for writing structured audit logs. | **Inactive** (Unwired) |
| `os_policy.py` | Defines allowed/restricted OS intents and role requirements. | **Inactive** (Unwired) |
| `policy_store.py` | Loads security policies from disk/defaults. | **Inactive** (Unwired) |
| `ratelimiter_redis.py` | Semantic rate limiter (Redis-backed with memory fallback). | **Inactive** (Unwired) |
| `guards.py` | Legacy guardrail implementation (likely superseded by `safety/`). | **Legacy** |

#### `kyrax_core/nlu/`
| File | Description |
| :--- | :--- |
| `llm_nlu.py` | **Primary NLU**. Uses Gemini to parse natural language into Intents/Entities. |
| `nlu_engine.py` | *Deprecated* spaCy-based keyword matcher. |

#### `kyrax_core/llm/`
| File | Description |
| :--- | :--- |
| `gemini_client.py` | Wrapper for Google's GenAI SDK (Gemini). |

#### `kyrax_core/safety/`
| File | Description |
| :--- | :--- |
| `confirmation_gate.py` | Defines logic for which commands require explicit user confirmation (e.g., shutdown). |

#### `kyrax_core/context/`
| File | Description |
| :--- | :--- |
| `pending_actions.py` | Simple store for holding actions that are awaiting confirmation. |

### `skills/` (The Effectors)
Modules that actually *do* things.

| File | Description | Status |
| :--- | :--- | :--- |
| **`whatsapp_skill.py`** | **Primary Skill.** Uses Playwright to drive WhatsApp Web. Sends messages. | **Active** |
| `os_skill.py` | Handles "os" domain commands (open app, volume). | **Available** |
| `os_backends.py` | implementation details for OS actions (platform specific logic). | **Active** |
| `iot_skill.py` | Handles "iot" domain (turn on lights). Currently simulated/stubbed. | **Demo** |

### `examples/` (Entry Points)
| File | Description | Status |
| :--- | :--- | :--- |
| **`run_pipeline.py`** | **MAIN ENTRY POINT.** The fully wired CLI application. Initializes NLU, Dispatcher, WhatsApp, etc. and runs the read-eval-print loop. | **Main** |
| `run_dispatcher.py` | Minimal script to test dispatching a hardcoded command. | **Utils** |
| `demo_*.py` | Various demo scripts showcasing specific components (Context, Reasoner, Guardrails) in isolation. | **Demo** |
| `test_*.py` | Unit/Integration tests for specific components. | **Test** |

### `server/`
*   **Status:** Empty.
*   **Note:** Originally intended for a FastAPI backend, but currently unimplemented.

### `tests/`
Contains `unittest`/`pytest` test suites for the core engine components.

### `data/`
| File | Description |
| :--- | :--- |
| `contacts.json` | JSON database of known contacts for resolution. |

## 5. System Architecture Flow
(As implemented in `run_pipeline.py`)

1.  **User Input** (Text) received.
2.  **Fast Path Check:** If it matches specific patterns (e.g., "send to X..."), bypass AI and build command directly.
3.  **Complex Reasoning:** If input is complex, **AIReasoner** (Gemini) breaks it down into a plan (list of steps).
4.  **NLU Analysis:** If simple but not a pattern, **LLMNLU** (Gemini) extracts Intent and Entities.
5.  **Command Building:** **CommandBuilder** validates the intent and resolves entities (e.g., "Mom" -> "+1234567890").
6.  **Dispatch:** **Dispatcher** finds the matching Skill.
7.  **Execution:** Skill performs the action (e.g., **WhatsAppSkill** launches Chrome and types).
8.  **Feedback:** Result is logged to **ContextLogger** for future reference.
