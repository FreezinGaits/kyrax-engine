from kyrax_core.policy_store import get_policy_store

ps = get_policy_store()
ps.reload()
print("Policy reloaded successfully")
