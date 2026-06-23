#!/usr/bin/env python3
"""
modules/ai_dev_lab — Self-Evolving AI Development Lab (SEADL)

A system that can discover problems, research solutions, design architectures,
generate code, test solutions, benchmark improvements, and evolve itself.

Sub-modules
-----------
lab_controller        — Orchestrate the entire AI lab
experiment_manager    — Manage experiment lifecycle
research_agent        — Gather supporting evidence from APIs
architecture_designer — Design software architectures
algorithm_inventor    — Invent new algorithms by combining patterns
code_synthesizer      — Generate executable implementations
benchmark_engine      — Evaluate implementations with metrics
experiment_database   — Store experiment results in SQLite
discovery_engine      — Detect performance breakthroughs
hypothesis_generator  — Generate research hypotheses automatically
evolution_engine      — Evolve Niblit's own architecture
safety_guard          — Validate code safety before execution
"""

from modules.ai_dev_lab.lab_controller import AIDevLab
from modules.ai_dev_lab.experiment_manager import ExperimentManager
from modules.ai_dev_lab.research_agent import ResearchAgent
from modules.ai_dev_lab.architecture_designer import ArchitectureDesigner
from modules.ai_dev_lab.algorithm_inventor import AlgorithmInventor
from modules.ai_dev_lab.code_synthesizer import CodeSynthesizer
from modules.ai_dev_lab.benchmark_engine import BenchmarkEngine
from modules.ai_dev_lab.experiment_database import ExperimentDatabase
from modules.ai_dev_lab.discovery_engine import DiscoveryEngine
from modules.ai_dev_lab.hypothesis_generator import HypothesisGenerator
from modules.ai_dev_lab.evolution_engine import EvolutionEngine
from modules.ai_dev_lab.safety_guard import SafetyGuard

__all__ = [
    "AIDevLab",
    "ExperimentManager",
    "ResearchAgent",
    "ArchitectureDesigner",
    "AlgorithmInventor",
    "CodeSynthesizer",
    "BenchmarkEngine",
    "ExperimentDatabase",
    "DiscoveryEngine",
    "HypothesisGenerator",
    "EvolutionEngine",
    "SafetyGuard",
]
if __name__ == "__main__":
    print('Running __init__.py')
