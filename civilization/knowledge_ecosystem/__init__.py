"""civilization.knowledge_ecosystem — vector/graph memory and knowledge API."""

from .embedding_service import EmbeddingService
from .graph_memory import GraphMemory
from .knowledge_api import KnowledgeAPI
from .vector_memory import VectorMemory

__all__ = ["VectorMemory", "GraphMemory", "EmbeddingService", "KnowledgeAPI"]
if __name__ == "__main__":
    print('Running __init__.py')
