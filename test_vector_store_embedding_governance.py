#!/usr/bin/env python3
"""Tests for embedding governance scoring configuration."""

from modules.vector_store import EmbeddingRuntimeConfig


def test_embedding_runtime_config_governed_score_applies_decay():
    cfg = EmbeddingRuntimeConfig(
        memory_relevance_weight=0.5,
        reflection_weight=0.2,
        replay_weight=0.1,
        coherence_factor=0.2,
        decay_influence=0.2,
    )
    score = cfg.govern_score(
        0.8,
        {
            "memory_relevance": 0.8,
            "reflection_weight": 0.5,
            "replay_weight": 0.4,
            "coherence_factor": 0.9,
            "decay_influence": 0.5,
        },
    )
    assert 0.0 <= score <= 1.0
    assert score < 0.8


def test_embedding_runtime_config_reads_env(monkeypatch):
    monkeypatch.setenv("NIBLIT_EMBED_MEMORY_WEIGHT", "0.4")
    monkeypatch.setenv("NIBLIT_EMBED_REFLECTION_WEIGHT", "0.2")
    monkeypatch.setenv("NIBLIT_EMBED_REPLAY_WEIGHT", "0.1")
    monkeypatch.setenv("NIBLIT_EMBED_COHERENCE_FACTOR", "0.2")
    monkeypatch.setenv("NIBLIT_EMBED_DECAY_INFLUENCE", "0.1")
    cfg = EmbeddingRuntimeConfig.from_env()
    assert cfg.memory_relevance_weight == 0.4
    assert cfg.decay_influence == 0.1


if __name__ == "__main__":
    print('Running test_vector_store_embedding_governance.py')
