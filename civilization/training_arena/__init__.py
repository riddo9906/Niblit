"""civilization.training_arena — challenge generation and competition infrastructure."""

from .arena_manager import ArenaManager
from .challenge_generator import ChallengeGenerator
from .competition_engine import CompetitionEngine
from .scoring_system import ScoringSystem

__all__ = ["ArenaManager", "ChallengeGenerator", "CompetitionEngine", "ScoringSystem"]
if __name__ == "__main__":
    print('Running __init__.py')
