# modules/dashboard.py
import os, json, time
from modules import llm_module

def terminal_dashboard(db, modules):
    """Print a compact terminal dashboard summary."""
    facts = len(db.data.get("facts", []))
    interactions = len(db.data.get("interactions", []))
    llm_key = bool(llm_module.HF_TOKEN)
    llm_online = llm_module.is_online() if llm_key else False
    lines = [
        "=== Niblit Dashboard ===",
        f"Facts stored:        {facts}",
        f"Interactions stored: {interactions}",
        f"LLM token present:   {llm_key}",
        f"LLM online:          {llm_online}",
        f"Available modules:   {', '.join(sorted(list(modules.keys())))}",
        f"Working dir:         {os.getcwd()}",
        f"Time:                {time.ctime()}",
        "========================",
    ]
    return "\n".join(lines)

def status_dict(db, modules):
    return {
        "facts": len(db.data.get("facts",[])),
        "interactions": len(db.data.get("interactions",[])),
        "llm_token_present": bool(llm_module.HF_TOKEN),
        "llm_online": llm_module.is_online() if llm_module.HF_TOKEN else False,
        "modules": sorted(list(modules.keys())),
        "cwd": os.getcwd(),
        "time": time.time()
    }
