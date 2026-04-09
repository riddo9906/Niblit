"""civilization.agent_population — diverse agent types for the civilisation."""

from .analyst_agent import AnalystAgent
from .base_agent import BaseAgent
from .builder_agent import BuilderAgent
from .evolution_agent import EvolutionAgent
from .planner_agent import PlannerAgent
from .research_agent import ResearchAgent

__all__ = [
    "BaseAgent",
    "ResearchAgent",
    "BuilderAgent",
    "PlannerAgent",
    "AnalystAgent",
    "EvolutionAgent",
]
if __name__ == "__main__":
    print('Running __init__.py')
