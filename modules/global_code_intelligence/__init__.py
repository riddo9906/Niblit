#!/usr/bin/env python3
"""
modules/global_code_intelligence — Global Code Intelligence Map (GCIM)

Turns the entire open-source ecosystem into a machine-readable intelligence
graph that Niblit can reason over.

Pipeline::

    Data Sources (GitHub, PyPI, npm, Stack Exchange)
            ↓
    Code Intelligence Pipeline
            ↓
    Knowledge Extraction
            ↓
    Global Code Graph
            ↓
    Niblit Reasoning Engine

Sub-modules
-----------
ecosystem_scanner     — Continuously scan the global code ecosystem
dependency_mapper     — Map technology dependency relationships
architecture_detector — Detect software architectures automatically
pattern_graph_builder — Build the knowledge graph
code_embedding_index  — Convert code to semantic vector index
knowledge_reasoner    — Answer architecture and pattern questions
discovery_engine      — Detect emerging technologies
"""

from modules.global_code_intelligence.ecosystem_scanner import EcosystemScanner
from modules.global_code_intelligence.dependency_mapper import DependencyMapper
from modules.global_code_intelligence.architecture_detector import ArchitectureDetector
from modules.global_code_intelligence.pattern_graph_builder import PatternGraphBuilder
from modules.global_code_intelligence.code_embedding_index import CodeEmbeddingIndex
from modules.global_code_intelligence.knowledge_reasoner import KnowledgeReasoner
from modules.global_code_intelligence.discovery_engine import DiscoveryEngine

__all__ = [
    "EcosystemScanner",
    "DependencyMapper",
    "ArchitectureDetector",
    "PatternGraphBuilder",
    "CodeEmbeddingIndex",
    "KnowledgeReasoner",
    "DiscoveryEngine",
]
if __name__ == "__main__":
    print('Running __init__.py')
