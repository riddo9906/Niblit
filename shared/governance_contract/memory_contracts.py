"""Canonical governed cognitive memory contracts for the Niblit ecosystem."""

from __future__ import annotations

import copy
import hashlib
import time
from typing import Any

from .compatibility_matrix import compatibility_metadata
from .constitutional_laws import constitutional_verdict
from .runtime_modes import normalize_runtime_mode
from .telemetry_contract import normalize_replay_metadata, normalize_telemetry

MEMORY_SCHEMA_VERSION = "1.0"
MEMORY_LIFECYCLE_STATES = ("hot", "warm", "cold", "archived")
CANONICAL_MEMORY_COLLECTIONS = (
    "episodic_memory",
    "semantic_memory",
    "reflection_memory",
    "governance_memory",
    "runtime_memory",
    "replay_memory",
    "telemetry_memory",
    "advisor_memory",
    "federation_memory",
    "execution_memory",
)

_COLLECTION_BLUEPRINTS: dict[str, dict[str, Any]] = {
    "episodic_memory": {
        "namespace": "cognition.episodic",
        "priority": 0.82,
        "default_lifecycle_state": "hot",
        "retention_days": 45,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "governance_state", "lifecycle.state", "federation_origin.node_id"],
    },
    "semantic_memory": {
        "namespace": "cognition.semantic",
        "priority": 0.78,
        "default_lifecycle_state": "warm",
        "retention_days": 365,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "governance_state", "indexing.tags", "indexing.keywords"],
    },
    "reflection_memory": {
        "namespace": "cognition.reflection",
        "priority": 0.88,
        "default_lifecycle_state": "warm",
        "retention_days": 180,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "governance_state", "advisor_lineage", "constitutional_alignment.allowed"],
    },
    "governance_memory": {
        "namespace": "governance.decisions",
        "priority": 0.97,
        "default_lifecycle_state": "hot",
        "retention_days": 730,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "governance_state", "constitutional_alignment.authority", "lifecycle.governance_locked"],
    },
    "runtime_memory": {
        "namespace": "runtime.snapshots",
        "priority": 0.76,
        "default_lifecycle_state": "hot",
        "retention_days": 60,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "telemetry.epoch_id", "telemetry.source", "federation_origin.node_id"],
    },
    "replay_memory": {
        "namespace": "replay.lineage",
        "priority": 0.95,
        "default_lifecycle_state": "warm",
        "retention_days": 730,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "replay_metadata.trace_id", "replay_metadata.causal_references", "lifecycle.governance_locked"],
    },
    "telemetry_memory": {
        "namespace": "telemetry.history",
        "priority": 0.70,
        "default_lifecycle_state": "warm",
        "retention_days": 30,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "telemetry.epoch_id", "telemetry.source"],
    },
    "advisor_memory": {
        "namespace": "advisors.debate",
        "priority": 0.84,
        "default_lifecycle_state": "warm",
        "retention_days": 120,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "advisor_lineage", "runtime_mode", "governance_state"],
    },
    "federation_memory": {
        "namespace": "federation.shared",
        "priority": 0.86,
        "default_lifecycle_state": "warm",
        "retention_days": 180,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "federation_origin.node_id", "federation_origin.role", "runtime_mode"],
    },
    "execution_memory": {
        "namespace": "execution.outcomes",
        "priority": 0.90,
        "default_lifecycle_state": "hot",
        "retention_days": 365,
        "vector_size": 384,
        "payload_indexes": ["trace_id", "runtime_mode", "governance_state", "replay_metadata.trace_id", "telemetry.source"],
    },
}

_RUNTIME_MODE_WEIGHT = {"normal": 1.0, "cautious": 0.94, "survival": 0.82, "lockdown": 0.68}
_LIFECYCLE_WEIGHT = {"hot": 1.0, "warm": 0.88, "cold": 0.72, "archived": 0.45}


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _summary(text: str, fallback: str = "") -> str:
    source = (text or fallback or "").strip()
    if not source:
        return ""
    if len(source) <= 240:
        return source
    trimmed = source[:240]
    last_space = trimmed.rfind(" ")
    if last_space > 120:
        return trimmed[:last_space].strip()
    return trimmed.strip()


def _stable_memory_id(text: str, payload: dict[str, Any], memory_type: str) -> str:
    trace_id = str((payload.get("replay_metadata") or {}).get("trace_id") or payload.get("trace_id") or "")
    seed = "::".join(
        [
            memory_type,
            trace_id,
            str(payload.get("timestamp") or payload.get("created_at") or int(time.time())),
            (text or payload.get("summary") or "")[:200],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:24]


def collection_blueprints(node_identity: str = "niblit_core") -> dict[str, dict[str, Any]]:
    """Return copy-paste-friendly canonical Qdrant collection blueprints."""
    blueprints = copy.deepcopy(_COLLECTION_BLUEPRINTS)
    for name, blueprint in blueprints.items():
        blueprint["collection_name"] = name
        blueprint["distance"] = "Cosine"
        blueprint["shard_key"] = f"{node_identity}:{name}"
        blueprint["replication_factor"] = 1
        blueprint["write_consistency_factor"] = 1
        blueprint["compatibility"] = compatibility_metadata({"memory_schema_version": MEMORY_SCHEMA_VERSION})
        blueprint["retention_policy"] = {
            "state": blueprint["default_lifecycle_state"],
            "retention_days": blueprint["retention_days"],
            "replay_preserved": True,
            "governance_lock_respected": True,
        }
    return blueprints


def normalize_memory_payload(
    payload: dict[str, Any] | None,
    *,
    text: str = "",
    memory_type: str = "semantic_memory",
    node_identity: str = "niblit_core",
    authority: str = "niblit_core",
    runtime_mode: str | None = None,
    governance_state: str | None = None,
) -> dict[str, Any]:
    """Normalize a governed memory payload with replay/federation-safe defaults."""
    src = copy.deepcopy(payload or {})
    normalized_memory_type = memory_type if memory_type in CANONICAL_MEMORY_COLLECTIONS else "semantic_memory"
    blueprint = collection_blueprints(node_identity=node_identity)[normalized_memory_type]
    now = int(src.get("timestamp") or src.get("created_at") or time.time())
    content_text = str(text or src.get("content_text") or src.get("text") or src.get("summary") or "").strip()
    normalized_runtime_mode = normalize_runtime_mode(
        runtime_mode
        or src.get("runtime_mode")
        or (src.get("runtime") or {}).get("mode")
        or (src.get("telemetry") or {}).get("runtime_mode")
        or "normal"
    )
    normalized_governance_state = str(
        governance_state or src.get("governance_state") or src.get("state") or "active"
    ).strip().lower()

    telemetry_seed = src.get("telemetry") if isinstance(src.get("telemetry"), dict) else src
    telemetry = normalize_telemetry(telemetry_seed)
    telemetry["runtime_mode"] = normalize_runtime_mode(telemetry.get("runtime_mode", normalized_runtime_mode))
    telemetry["governance_mode"] = normalize_runtime_mode(
        telemetry.get("governance_mode", normalized_runtime_mode)
    )
    replay_seed = src.get("replay_metadata") if isinstance(src.get("replay_metadata"), dict) else src
    replay_metadata = normalize_replay_metadata(replay_seed)

    lifecycle = dict(src.get("lifecycle") or {})
    lifecycle_state = str(lifecycle.get("state", blueprint["default_lifecycle_state"]))
    if lifecycle_state not in MEMORY_LIFECYCLE_STATES:
        lifecycle_state = blueprint["default_lifecycle_state"]

    importance_score = _clamp(src.get("importance_score", src.get("importance", 0.5)), 0.5)
    reinforcement_score = _clamp(lifecycle.get("reinforcement_score", importance_score), importance_score)
    coherence_score = _clamp(
        src.get("coherence_score", (src.get("temporal") or {}).get("coherence_score", telemetry.get("coherence_score", 1.0))),
        1.0,
    )
    confidence_decay = _clamp(src.get("confidence_decay", lifecycle.get("confidence_decay", 0.0)), 0.0)
    constitutional = src.get("constitutional_alignment") if isinstance(src.get("constitutional_alignment"), dict) else {}
    constitutional_context = {
        "stability_score": coherence_score,
        "coherence_score": coherence_score,
        "confidence": max(0.0, 1.0 - confidence_decay),
        "autonomous": normalized_governance_state not in {"manual_only", "blocked"},
    }
    verdict = constitutional_verdict(constitutional_context)
    constitutional_alignment = {
        "allowed": bool(constitutional.get("allowed", verdict["allowed"])),
        "authority": str(constitutional.get("authority", verdict["authority"])),
        "violated_laws": list(constitutional.get("violated_laws", verdict["violated_laws"])),
    }

    advisor_lineage = _as_list(src.get("advisor_lineage") or (src.get("advisors") or {}).get("votes"))
    causal_chain = [str(item) for item in _as_list(src.get("causal_chain") or replay_metadata.get("causal_references"))]
    federation_origin = src.get("federation_origin") if isinstance(src.get("federation_origin"), dict) else {}
    federation_origin = {
        "node_id": str(federation_origin.get("node_id", node_identity)),
        "role": str(federation_origin.get("role", "governance_authority")),
        "authority": str(federation_origin.get("authority", authority)),
    }

    out: dict[str, Any] = {
        "memory_schema_version": MEMORY_SCHEMA_VERSION,
        "memory_id": str(src.get("memory_id") or _stable_memory_id(content_text, src, normalized_memory_type)),
        "memory_type": normalized_memory_type,
        "collection": normalized_memory_type,
        "content_text": content_text,
        "summary": str(src.get("summary") or _summary(content_text, str(src.get("reflection_summary") or ""))),
        "timestamp": now,
        "created_at": int(src.get("created_at", now)),
        "last_updated_at": int(src.get("last_updated_at", now)),
        "last_accessed_at": int(src.get("last_accessed_at", now)),
        "runtime_mode": normalized_runtime_mode,
        "governance_state": normalized_governance_state,
        "coherence_score": coherence_score,
        "confidence_decay": confidence_decay,
        "importance_score": importance_score,
        "federation_origin": federation_origin,
        "advisor_lineage": [str(item) for item in advisor_lineage],
        "reflection_summary": str(src.get("reflection_summary") or _summary(str(src.get("summary") or content_text))),
        "causal_chain": causal_chain,
        "replay_metadata": replay_metadata,
        "constitutional_alignment": constitutional_alignment,
        "telemetry_signature": hashlib.sha1(
            repr(sorted(telemetry.items())).encode("utf-8", errors="replace")
        ).hexdigest()[:16],
        "telemetry": telemetry,
        "lifecycle": {
            "state": lifecycle_state,
            "reinforcement_score": reinforcement_score,
            "pinned": bool(lifecycle.get("pinned", False)),
            "governance_locked": bool(lifecycle.get("governance_locked", normalized_memory_type in {"governance_memory", "replay_memory"})),
            "archive_candidate": bool(lifecycle.get("archive_candidate", False)),
            "retention_days": int(lifecycle.get("retention_days", blueprint["retention_days"])),
        },
        "routing": {
            "namespace": str((src.get("routing") or {}).get("namespace", blueprint["namespace"])),
            "priority": _clamp((src.get("routing") or {}).get("priority", blueprint["priority"]), blueprint["priority"]),
            "shard_key": str((src.get("routing") or {}).get("shard_key", blueprint["shard_key"])),
            "replication_scope": str((src.get("routing") or {}).get("replication_scope", "federated")),
        },
        "indexing": {
            "keywords": [str(item) for item in _as_list((src.get("indexing") or {}).get("keywords"))],
            "tags": [str(item) for item in _as_list((src.get("indexing") or {}).get("tags"))],
            "runtime_mode": normalized_runtime_mode,
            "governance_state": normalized_governance_state,
        },
        "compatibility": compatibility_metadata({"memory_schema_version": MEMORY_SCHEMA_VERSION}),
    }
    return out


def validate_memory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a governed memory payload and return normalized output."""
    raw = dict(payload or {})
    normalized = normalize_memory_payload(raw, memory_type=str(raw.get("memory_type") or "semantic_memory"))
    issues: list[str] = []

    if normalized["memory_type"] not in CANONICAL_MEMORY_COLLECTIONS:
        issues.append("memory_type_invalid")
    if not normalized["content_text"] and not normalized["summary"]:
        issues.append("memory_content_missing")
    if normalized["lifecycle"]["state"] not in MEMORY_LIFECYCLE_STATES:
        issues.append("lifecycle_state_invalid")
    if not normalized["federation_origin"]["node_id"]:
        issues.append("federation_origin_missing")
    if not normalized["replay_metadata"]["trace_id"]:
        issues.append("trace_id_missing")
    if normalized["memory_schema_version"] != MEMORY_SCHEMA_VERSION:
        issues.append("memory_schema_version_mismatch")

    raw_lifecycle = raw.get("lifecycle")
    if raw_lifecycle is not None and not isinstance(raw_lifecycle, dict):
        issues.append("lifecycle_invalid")
    raw_federation = raw.get("federation_origin")
    if raw_federation is not None and not isinstance(raw_federation, dict):
        issues.append("federation_origin_invalid")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "normalized": normalized,
    }


def governed_recall_allowed(
    payload: dict[str, Any] | None,
    *,
    runtime_mode: str = "normal",
    governance_state: str = "active",
) -> bool:
    """Return whether a memory is eligible for recall under current governance."""
    normalized = normalize_memory_payload(payload, memory_type=str((payload or {}).get("memory_type") or "semantic_memory"))
    if not normalized["constitutional_alignment"]["allowed"]:
        return False
    if normalized["governance_state"] in {"blocked", "quarantined"}:
        return False
    if normalized["lifecycle"]["governance_locked"] and governance_state not in {"override", "review"}:
        return False
    if normalized["lifecycle"]["state"] == "archived" and normalize_runtime_mode(runtime_mode) in {"survival", "lockdown"}:
        return False
    return True


def memory_retrieval_score(
    payload: dict[str, Any] | None,
    *,
    base_score: float = 0.0,
    runtime_mode: str = "normal",
) -> float:
    """Compute an explainable governance-aware retrieval score."""
    normalized = normalize_memory_payload(payload, memory_type=str((payload or {}).get("memory_type") or "semantic_memory"))
    lifecycle_state = normalized["lifecycle"]["state"]
    runtime_weight = _RUNTIME_MODE_WEIGHT[normalize_runtime_mode(runtime_mode)]
    lifecycle_weight = _LIFECYCLE_WEIGHT[lifecycle_state]
    reinforcement = normalized["lifecycle"]["reinforcement_score"]
    score = (
        max(0.0, float(base_score)) * 0.45
        + normalized["importance_score"] * 0.20
        + normalized["coherence_score"] * 0.15
        + reinforcement * 0.10
        + normalized["routing"]["priority"] * 0.10
    )
    score *= runtime_weight * lifecycle_weight
    score -= normalized["confidence_decay"] * 0.18
    if normalized["lifecycle"]["pinned"]:
        score += 0.08
    if normalized["lifecycle"]["governance_locked"]:
        score += 0.05
    return round(max(0.0, min(1.0, score)), 6)


def transition_memory_lifecycle(
    payload: dict[str, Any] | None,
    *,
    runtime_pressure: float = 0.0,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Apply governed lifecycle transitions while preserving replay determinism."""
    normalized = normalize_memory_payload(payload, memory_type=str((payload or {}).get("memory_type") or "semantic_memory"))
    current = normalized["lifecycle"]["state"]
    pinned = normalized["lifecycle"]["pinned"]
    governance_locked = normalized["lifecycle"]["governance_locked"]
    replay_trace = normalized["replay_metadata"].get("trace_id")
    reinforcement = normalized["lifecycle"]["reinforcement_score"]
    pressure = _clamp(runtime_pressure, 0.0)
    ts = int(now_ts or time.time())
    last_touch_value = normalized.get("last_accessed_at")
    if last_touch_value is None:
        last_touch_value = normalized.get("last_updated_at")
    if last_touch_value is None:
        last_touch_value = normalized.get("timestamp")
    last_touch = int(last_touch_value if last_touch_value is not None else ts)
    age_days = max(0.0, (ts - last_touch) / 86400.0)

    target = current
    action = "retain"
    if pinned:
        target = current
        action = "retain"
    elif age_days >= 90 or (pressure >= 0.85 and reinforcement < 0.35):
        target = "archived" if replay_trace else "cold"
        action = "archive" if target == "archived" else "cool"
    elif age_days >= 30 or pressure >= 0.60:
        target = "cold"
        action = "cool"
    elif age_days >= 7 or pressure >= 0.35:
        target = "warm"
        action = "warm"
    else:
        target = "hot"
        action = "promote" if current != "hot" else "retain"

    if governance_locked and target != "archived":
        target = current
        action = "retain"
    if replay_trace and target == "archived":
        action = "archive"
    elif replay_trace and target == "cold":
        action = "preserve_replay"
    if normalized["memory_type"] in {"governance_memory", "replay_memory"} and target == "archived":
        normalized["lifecycle"]["governance_locked"] = True

    normalized["lifecycle"]["state"] = target
    normalized["lifecycle"]["archive_candidate"] = target in {"cold", "archived"} and not pinned
    normalized["last_updated_at"] = ts

    return {
        "updated": normalized,
        "previous_state": current,
        "state": target,
        "action": action,
        "age_days": round(age_days, 3),
    }


def reconstruct_memory_lineage(records: list[dict[str, Any]] | None, trace_id: str | None = None) -> dict[str, Any]:
    """Reconstruct replay-safe lineage from governed memory records."""
    normalized_records = [
        normalize_memory_payload(item, memory_type=str((item or {}).get("memory_type") or "semantic_memory"))
        for item in (records or [])
    ]
    if trace_id:
        normalized_records = [
            item
            for item in normalized_records
            if item["replay_metadata"].get("trace_id") == trace_id or item["memory_id"] == trace_id
        ]
    normalized_records.sort(
        key=lambda item: (
            item["replay_metadata"].get("trace_id", ""),
            item.get("timestamp", 0),
            item.get("memory_id", ""),
        )
    )
    causal_chain: list[str] = []
    ordered_ids: list[str] = []
    governance_states: list[str] = []
    runtime_modes: list[str] = []
    collections: dict[str, int] = {}
    for item in normalized_records:
        ordered_ids.append(item["memory_id"])
        governance_states.append(item["governance_state"])
        runtime_modes.append(item["runtime_mode"])
        collections[item["memory_type"]] = collections.get(item["memory_type"], 0) + 1
        for link in item["causal_chain"]:
            if link not in causal_chain:
                causal_chain.append(link)
    return {
        "trace_id": trace_id or (normalized_records[0]["replay_metadata"].get("trace_id") if normalized_records else ""),
        "ordered_memory_ids": ordered_ids,
        "governance_states": governance_states,
        "runtime_modes": runtime_modes,
        "causal_chain": causal_chain,
        "collection_counts": collections,
        "records": normalized_records,
    }


def detect_memory_drift(records: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Detect schema/payload drift across governed memory records."""
    drift_issues: list[str] = []
    invalid_records = 0
    unknown_runtime_modes = 0
    for record in records or []:
        check = validate_memory_payload(record)
        if not check["valid"]:
            invalid_records += 1
            drift_issues.extend(check["issues"])
        runtime_mode = str((record or {}).get("runtime_mode") or (record or {}).get("telemetry", {}).get("runtime_mode") or "normal")
        if normalize_runtime_mode(runtime_mode) != runtime_mode and runtime_mode not in {"normal", "cautious", "survival", "lockdown"}:
            unknown_runtime_modes += 1
            drift_issues.append("runtime_mode_alias_or_unknown")
    unique_issues = sorted(set(drift_issues))
    return {
        "drift_risk": "low" if not unique_issues else ("medium" if len(unique_issues) == 1 else "high"),
        "invalid_records": invalid_records,
        "unknown_runtime_modes": unknown_runtime_modes,
        "issues": unique_issues,
    }
