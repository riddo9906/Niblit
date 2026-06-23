import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class QdrantConfig:
    url: str
    api_key: Optional[str]
    collection: str
    prefix: str

    @staticmethod
    def load() -> "QdrantConfig":
        return QdrantConfig(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY", None),
            collection=os.getenv("QDRANT_COLLECTION", "niblit_vectors"),
            prefix=os.getenv("QDRANT_COLLECTION_PREFIX", "niblit"),
        )

