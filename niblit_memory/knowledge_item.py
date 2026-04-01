from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class KnowledgeItem:
    id: str
    topic: str
    summary: str = ""
    source: str = ""
    date_added: str = ""
    confidence: float = 0.0
    tags: List[str] = field(default_factory=list)
    related_items: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
