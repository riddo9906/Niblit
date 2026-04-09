#!/usr/bin/env python3
"""
modules/knowledge_engine — Self-Expanding Knowledge Engine (SEKE)

Continuously scans the global software ecosystem, extracts patterns and
architectures, converts them to machine-readable knowledge, and feeds the
results into the Niblit intelligence layer.

Pipeline::

    Repository Scanner
          ↓
    Code Extraction Layer
          ↓
    Pattern Intelligence
          ↓
    Knowledge Generator
          ↓
    Vector + Graph Store
          ↓
       NIBLIT BRAIN

Sub-modules
-----------
repo_scanner         — GitHub API-based continuous repo discovery
repo_downloader      — Shallow-clone repos for local analysis
code_parser          — AST-based function/class/import extraction
pattern_extractor    — Design-pattern detection (singleton, factory, etc.)
architecture_analyzer— High-level software architecture recognition
embedding_pipeline   — Code → vector embeddings via VectorStore
knowledge_graph_builder — Build networkx knowledge graph
learning_scheduler   — Coordinating and scheduling the full pipeline
"""

from modules.knowledge_engine.repo_scanner import RepoScanner
from modules.knowledge_engine.repo_downloader import RepoDownloader
from modules.knowledge_engine.code_parser import CodeParser
from modules.knowledge_engine.pattern_extractor import PatternExtractor
from modules.knowledge_engine.architecture_analyzer import ArchitectureAnalyzer
from modules.knowledge_engine.embedding_pipeline import EmbeddingPipeline
from modules.knowledge_engine.knowledge_graph_builder import KnowledgeGraphBuilder
from modules.knowledge_engine.learning_scheduler import LearningScheduler

__all__ = [
    "RepoScanner",
    "RepoDownloader",
    "CodeParser",
    "PatternExtractor",
    "ArchitectureAnalyzer",
    "EmbeddingPipeline",
    "KnowledgeGraphBuilder",
    "LearningScheduler",
]
if __name__ == "__main__":
    print('Running __init__.py')
