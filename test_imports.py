#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

try:
    from modules.local_brain import (
        get_local_brain,
        LocalBrainGateway,
        NIBLIT_ALL_TOOLS,
        NIBLIT_KB_TOOLS,
        NIBLIT_SLIM_TOOLS,
        QwenLocalBrain,
        BrainTrainer,
        NiblitCloudBrain,
        swap_local_brain,
        set_backend_url,
        get_backend_info,
        acquire_model_lock,
        release_model_lock,
        _GGUF_TEMPLATES,
        _build_gguf_prompt,
        _clean_subprocess_output,
        _resolve_portable_model_path,
        _LocalBrainConfig,
        _cfg,
        _MAX_NEW_TOKENS,
        _GGUF_N_CTX,
        _LOCAL_MODEL_PRESETS,
        _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT,
        _SHORT_CHAT_SYSTEM_PROMPT,
        _TOOL_CALL_SYSTEM_PROMPT,
        _NIBLIT_FULL_STRUCTURAL_CONTEXT,
    )
    print("All imports OK")
    
    # Test LocalBrainGateway
    gw = LocalBrainGateway()
    status = gw.status()
    print(f"Gateway status: {status['local_brain']}")
    
    # Test backwards compat
    print(f"Legacy QwenLocalBrain: {QwenLocalBrain}")
    print(f"Legacy BrainTrainer: {BrainTrainer}")
    print(f"Legacy NiblitCloudBrain: {NiblitCloudBrain}")
    
except Exception as e:
    print(f"FAIL: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)