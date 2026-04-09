"""civilization.evolution_engine — mutation, selection, and architecture evolution."""

from .architecture_evolver import ArchitectureEvolver
from .mutation_engine import MutationEngine
from .population_optimizer import PopulationOptimizer
from .selection_engine import SelectionEngine

__all__ = ["MutationEngine", "SelectionEngine", "PopulationOptimizer", "ArchitectureEvolver"]
if __name__ == "__main__":
    print('Running __init__.py')
