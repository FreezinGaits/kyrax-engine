# # server/intent_handler.py  (pseudo-code snippet)
# from kyrax_core.planner_pipeline import plan_validate_and_dispatch
# from kyrax_core.context_logger import ContextLogger
# from your_real_dispatcher_module import RealDispatcher  # your implementation

# context_logger = ContextLogger()  # or reuse existing instance in your server
# dispatcher = RealDispatcher()     # your real dispatcher instance

# def handle_goal_intent(goal_text: str):
#     results, issues = plan_validate_and_dispatch(
#         goal_text=goal_text,
#         dispatcher=dispatcher,
#         context_logger=context_logger
#     )
#     # respond to user
#     if issues:
#         # ask for clarification or log
#         return {"status": "partial", "results": results, "issues": issues}
#     return {"status": "ok", "results": results}
