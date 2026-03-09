import os, time
from modules.llm_module import HFLLMAdapter

def terminal_dashboard(db, modules):
    facts = len(db.data.get("facts", []))
    interactions = len(db.data.get("interactions", []))
    hf_adapter = HFLLMAdapter()
    llm_key = bool(hf_adapter.api_key)
    llm_online = hf_adapter.is_online() if llm_key else False
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
    hf_adapter = HFLLMAdapter()
    return {
        "facts": len(db.data.get("facts",[])),
        "interactions": len(db.data.get("interactions",[])),
        "llm_token_present": bool(hf_adapter.api_key),
        "llm_online": hf_adapter.is_online() if hf_adapter.api_key else False,
        "modules": sorted(list(modules.keys())),
        "cwd": os.getcwd(),
        "time": time.time()
    }
if __name__ == "__main__":
    print('Running dashboard.py')
