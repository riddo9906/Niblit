"""
agents/ — Niblit next-gen agent architecture package (Phase 2).

Import from here::

    from agents import (
        BaseAgent,
        PlannerAgent,
        ResearchAgent,
        CodingAgent,
        TestingAgent,
        ReflectionAgent,
        ArchitectureAgent,
    )
"""

from agents.architecture_agent import ArchitectureAgent
from agents.base_agent import AgentState, BaseAgent
from agents.coding_agent import CodingAgent
from agents.document_cognition_agent import DocumentCognitionAgent
from agents.niblit_dev_agent import NiblitDevAgent
from agents.planner_agent import PlannerAgent
from agents.reflection_agent import ReflectionAgent
from agents.research_agent import ResearchAgent
from agents.testing_agent import TestingAgent

__all__ = [
    "BaseAgent",
    "AgentState",
    "PlannerAgent",
    "ResearchAgent",
    "CodingAgent",
    "DocumentCognitionAgent",
    "TestingAgent",
    "ReflectionAgent",
    "ArchitectureAgent",
    "NiblitDevAgent",
]
if __name__ == "__main__":
    print('Running __init__.py')
