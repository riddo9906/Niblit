"""Explicit 14B desktop inference via verified separate Niblit Cloud service.

No model loads, no paid/provider fallback, no broker actions. Existing
NiblitCloudBrain route for 3B and other models is unchanged.
"""
from niblit_brain import NiblitCloudBrain, get_niblit_cloud_brain

FOUR_MODEL_CLOUD = "http://127.0.0.1:8212"
LARGE_MODEL_ID = "qwen2.5-coder-14b"


def selected_cloud_brain(model_id: str):
    if model_id == LARGE_MODEL_ID:
        return NiblitCloudBrain(base_url=FOUR_MODEL_CLOUD, timeout=240)
    return get_niblit_cloud_brain()


async def additional_local_models() -> list[dict[str, str]]:
    """Advertise large model only when the verified Cloud names it."""
    try:
        result = await NiblitCloudBrain(base_url=FOUR_MODEL_CLOUD, timeout=3).list_models()
        matches = [row for row in result.get("data", []) if isinstance(row,dict)
                   and row.get("id") == LARGE_MODEL_ID]
        return [{"id": LARGE_MODEL_ID, "object": "model"}] if matches else []
    except (RuntimeError, TypeError, ValueError):
        return []
