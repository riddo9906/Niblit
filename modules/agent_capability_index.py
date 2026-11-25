"""Structured capability retrieval and provider-scope filtering for Niblit agents.

Retrieval uses BM25 (Robertson/Sparck Jones family) over weighted, typed
capability fields. Provider scope is a hard eligibility constraint, not a
ranking preference: a workspace-scoped provider cannot be selected for a path
outside its configured roots. The index only narrows the caller's allow-list.
"""
from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import PureWindowsPath
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\|\\\\)[^\s\"'<>|]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could",
    "do", "does", "for", "from", "get", "give", "i", "in", "is", "it",
    "me", "my", "of", "on", "or", "please", "show", "tell", "that",
    "the", "this", "to", "use", "using", "we", "what", "which", "with",
}


def tokenize(value: Any) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return [token for token in _TOKEN_RE.findall(normalized) if token not in _STOP_WORDS]


def extract_windows_paths(query: str) -> list[str]:
    paths: list[str] = []
    for match in _WINDOWS_ABSOLUTE_PATH_RE.findall(query or ""):
        candidate = match.rstrip(".,;:!?)]}")
        if PureWindowsPath(candidate).is_absolute() and candidate not in paths:
            paths.append(candidate)
    return paths


def _normal_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def path_is_within_roots(path: str, roots: list[str]) -> bool:
    target = _normal_path(path)
    for root in roots:
        try:
            normalized_root = _normal_path(root)
            if os.path.commonpath([target, normalized_root]) == normalized_root:
                return True
        except (OSError, ValueError):
            continue
    return False


def filter_by_provider_scope(query: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude workspace/repository tools when requested absolute paths escape their roots."""
    paths = extract_windows_paths(query)
    explicit_desktop_commander = bool(re.search(r"(?i)desktop[\s_-]+commander", query or ""))
    eligible: list[dict[str, Any]] = []
    for record in records:
        metadata = record.get("metadata") or {}
        provider = str(metadata.get("provider") or "")
        scope = str(metadata.get("scope") or "")
        roots = metadata.get("allowed_roots") or []

        if explicit_desktop_commander and scope in {"host_filesystem", "workspace_filesystem"}:
            if provider != "desktop_commander":
                continue

        if paths and scope in {"workspace_filesystem", "repository"}:
            if not all(path_is_within_roots(path, roots) for path in paths):
                continue
        eligible.append(record)
    return eligible


def _weighted_document(record: dict[str, Any]) -> Counter[str]:
    schema = record.get("schema") or {}
    function = schema.get("function") or {}
    parameters = function.get("parameters") or {}
    properties = parameters.get("properties") or {}
    metadata = record.get("metadata") or {}
    terms: Counter[str] = Counter()

    def add(value: Any, weight: float) -> None:
        for token in tokenize(value):
            terms[token] += weight

    add(record.get("name"), 3.0)
    add(function.get("name"), 2.0)
    add(function.get("description"), 1.0)
    add(metadata.get("provider"), 1.5)
    add(metadata.get("scope"), 1.5)
    add(metadata.get("category"), 1.5)
    for keyword in metadata.get("keywords") or []:
        add(keyword, 2.5)
    for parameter_name, parameter in properties.items():
        add(parameter_name, 2.0)
        add((parameter or {}).get("description"), 1.0)
    return terms


def rank_capabilities(
    query: str,
    records: list[dict[str, Any]],
    *,
    top_k: int = 12,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[str]:
    """Rank eligible tools using field-weighted BM25; ties are deterministic."""
    if not records or top_k <= 0:
        return []
    query_terms = tokenize(query)
    if not query_terms:
        return [str(item.get("name")) for item in sorted(records, key=lambda item: str(item.get("name")))[:top_k]]

    documents = [_weighted_document(record) for record in records]
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / max(1, len(lengths))
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())

    query_frequency = Counter(query_terms)
    scored: list[tuple[float, str]] = []
    count = len(records)
    for record, document, document_length in zip(records, documents, lengths):
        score = 0.0
        for term, qtf in query_frequency.items():
            frequency = document.get(term, 0.0)
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_frequency = math.log(
                1.0 + (count - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + k1 * (
                1.0 - b + b * document_length / max(1.0, average_length)
            )
            score += inverse_frequency * (
                frequency * (k1 + 1.0) / denominator
            ) * (1.0 + math.log(qtf))
        scored.append((score, str(record.get("name"))))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored[:top_k]]


def retrieve_capabilities(
    query: str,
    schemas: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, Any]] | None = None,
    *,
    top_k: int = 12,
) -> list[str]:
    """Apply hard provider scope first, then BM25 ranking within the allow-list."""
    metadata = metadata or {}
    records = [
        {"name": name, "schema": schema, "metadata": metadata.get(name, {})}
        for name, schema in schemas.items()
    ]
    eligible = filter_by_provider_scope(query, records)
    return rank_capabilities(query, eligible, top_k=top_k)
