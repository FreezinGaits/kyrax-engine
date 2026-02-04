# Archive - Deprecated/Unused Files

This folder contains files that are **not used** in the current KYRAX pipeline or have been **superseded** by better implementations.

## Files Archived

### Broken / Superseded Core

- `planner_pipeline.py` - Broken API (calls `dispatcher.dispatch()` which didn't exist), double execution bug. Use `AIReasoner` + `ChainExecutor` instead.
- `planner.py` - Template-based planner superseded by `AIReasoner` for natural language input. Can be reintroduced as a macro library if needed.
- `nlu_engine.py` - spaCy-based NLU unused in production pipeline. Main pipeline uses `LLMNLU` (Gemini-backed).

### Unwired Adapters

- `text_adapter.py` - CLI adapter not used (run_pipeline uses `input()` directly)
- `api_adapter.py` - FastAPI adapter not wired to real pipeline
- `voice_adapter.py` - Voice adapter not integrated into main pipeline

### Broken Demos

- `demo_planner_pipeline.py` - Demonstrates broken `planner_pipeline` design
- `demo_planner.py` - Demonstrates outdated template planner

### Stubs

- `intent_handler.py` - Comment-only stub, not runnable

## Current Architecture

The active pipeline (`examples/run_pipeline.py`) uses:

- **LLM Adapters** (`llm_adapters.py`) - Abstraction for Gemini/OpenAI
- **AIReasoner** - Natural language planning
- **ChainExecutor** - Multi-step execution with placeholder resolution
- **WorkflowManager** - Persistence (optional)
- **LLMNLU** - Gemini-backed NLU
- **Dispatcher** - Execution router (now has both `execute()` and `dispatch()` methods)
