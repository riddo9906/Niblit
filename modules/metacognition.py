#!/usr/bin/env python3
"""
METACOGNITION MODULE
Know what you know — understand own knowledge and limitations.

Enhancements (additive — all original methods fully preserved):
  • ProvenanceRecord: dataclass capturing source, agent, rationale, and
    confidence for every knowledge item.
  • Metacognition.record_provenance(): register source/rationale for any
    fact key so that confidence can be explained later.
  • Metacognition.get_confidence_snapshot(): returns a serialisable dict
    with per-key confidence scores, source citations, and overall metrics
    — intended for the CLI 'confidence' command.
  • Metacognition.get_confidence_parse_tree(): returns a nested dict
    ("parse tree") breaking confidence down by category and confidence tier.
  • Original evaluate_understanding() is unchanged; new
    evaluate_understanding_rich() adds source provenance to the output.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("Metacognition")


# ══════════════════════════════════════════════════════════════════════════════
# ProvenanceRecord — tracks source, agent, and rationale per knowledge item
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProvenanceRecord:
    """
    Captures the provenance (origin/rationale) of a single knowledge item.

    Fields
    ------
    key:        Fact/knowledge key (e.g. "ale_learned:topic:timestamp").
    source:     Source URL, agent name, or dataset identifier.
    agent:      Name of the agent that produced this fact (e.g. "research_agent").
    rationale:  Human-readable explanation of why this fact was stored.
    confidence: Float 0.0–1.0 estimated confidence.
    ts:         Unix timestamp when provenance was recorded.
    """
    key: str
    source: str = "unknown"
    agent: str = "unknown"
    rationale: str = ""
    confidence: float = 0.5
    ts: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "agent": self.agent,
            "rationale": self.rationale,
            "confidence": round(self.confidence, 4),
            "ts": self.ts,
        }


class Metacognition:
    """Self-aware knowledge evaluation"""
    
    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.knowledge_map = {}
        self.confidence_levels = {}
        self.knowledge_boundaries = set()
        # Additive: provenance registry keyed by fact key
        self._provenance: Dict[str, ProvenanceRecord] = {}
    
    def build_knowledge_map(self, facts: List[Dict]) -> Dict[str, Any]:
        """
        Map what Niblit knows
        Track confidence levels and boundaries
        """
        log.info(f"🧠 [META] Building knowledge map from {len(facts)} facts")
        
        knowledge_map = {
            "total_facts": len(facts),
            "categories": {},
            "high_confidence": [],
            "medium_confidence": [],
            "low_confidence": [],
            "uncertain": []
        }
        
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "general"
            
            if category not in knowledge_map["categories"]:
                knowledge_map["categories"][category] = 0
            knowledge_map["categories"][category] += 1
            
            # Estimate confidence based on source
            confidence = self._estimate_confidence(fact)
            if confidence >= 0.8:
                knowledge_map["high_confidence"].append(key)
            elif confidence >= 0.5:
                knowledge_map["medium_confidence"].append(key)
            elif confidence >= 0.2:
                knowledge_map["low_confidence"].append(key)
            else:
                knowledge_map["uncertain"].append(key)
        
        self.knowledge_map = knowledge_map
        log.info(f"✅ [META] Knowledge map built")
        return knowledge_map
    
    def identify_knowledge_boundaries(self, attempted_topics: List[str]) -> Dict[str, List[str]]:
        """
        Identify where knowledge ends
        Recognize what Niblit doesn't know well
        """
        log.info(f"🚧 [META] Identifying knowledge boundaries")
        
        boundaries = {
            "well_understood": [],
            "partially_understood": [],
            "poorly_understood": [],
            "unknown": []
        }
        
        for topic in attempted_topics:
            # Check if in knowledge map
            topic_facts = [f for f in self.knowledge_map.get("high_confidence", []) if topic in f]
            
            if len(topic_facts) > 5:
                boundaries["well_understood"].append(topic)
            elif len(topic_facts) > 2:
                boundaries["partially_understood"].append(topic)
            elif len(topic_facts) > 0:
                boundaries["poorly_understood"].append(topic)
            else:
                boundaries["unknown"].append(topic)
        
        self.knowledge_boundaries = set(attempted_topics)
        log.info(f"✅ [META] Boundaries identified")
        return boundaries
    
    def evaluate_understanding(self) -> Dict[str, Any]:
        """
        Self-evaluate overall understanding
        """
        log.info(f"📊 [META] Evaluating understanding")
        
        total = len(self.knowledge_map.get("high_confidence", [])) + \
                len(self.knowledge_map.get("medium_confidence", [])) + \
                len(self.knowledge_map.get("low_confidence", []))
        
        evaluation = {
            "total_knowledge_items": self.knowledge_map.get("total_facts", 0),
            "high_confidence_facts": len(self.knowledge_map.get("high_confidence", [])),
            "medium_confidence_facts": len(self.knowledge_map.get("medium_confidence", [])),
            "low_confidence_facts": len(self.knowledge_map.get("low_confidence", [])),
            "uncertain_facts": len(self.knowledge_map.get("uncertain", [])),
            "overall_confidence": f"{(len(self.knowledge_map.get('high_confidence', [])) / max(1, total)) * 100:.1f}%",
            "knowledge_quality": "Good" if total > 50 else "Developing",
            "recommendation": "Continue learning to increase confidence across more domains"
        }
        
        log.info(f"✅ [META] Evaluation: {evaluation['overall_confidence']} confidence")
        return evaluation
    
    def _estimate_confidence(self, fact: Dict) -> float:
        """
        Estimate confidence in a fact
        Based on source and tags
        """
        source = fact.get("source", "unknown").lower()
        tags = fact.get("tags", [])
        
        confidence = 0.5  # Base confidence
        
        # Higher confidence for academic sources
        if "wikipedia" in source or "academic" in source:
            confidence += 0.2
        elif "research" in tags:
            confidence += 0.15
        elif "web" in tags:
            confidence += 0.1
        
        # Reduce for uncertain tags
        if "uncertain" in tags:
            confidence -= 0.2
        if "preliminary" in tags:
            confidence -= 0.15
        
        return min(1.0, max(0.0, confidence))

    # ══════════════════════════════════════════════════════════════════════
    # ADDITIVE ENHANCEMENTS — provenance tracking and confidence API
    # ══════════════════════════════════════════════════════════════════════

    def record_provenance(
        self,
        key: str,
        source: str = "unknown",
        agent: str = "unknown",
        rationale: str = "",
        confidence: Optional[float] = None,
        fact: Optional[Dict] = None,
    ) -> ProvenanceRecord:
        """
        Register source, agent, and rationale for a knowledge item.

        Called by any agent that stores a fact so that later confidence
        queries can return a full explanation.  If *confidence* is None it
        is estimated from *fact* using _estimate_confidence().

        Parameters
        ----------
        key:        Fact/knowledge key stored in the KnowledgeDB.
        source:     URL, dataset name, or agent output identifier.
        agent:      Agent name (e.g. 'research_agent', 'reflection_agent').
        rationale:  Why this fact was considered worth storing.
        confidence: Override confidence (0–1).  Estimated if None.
        fact:       Raw fact dict (used for confidence estimation if *confidence* is None).
        """
        if confidence is None:
            confidence = self._estimate_confidence(fact or {})

        rec = ProvenanceRecord(
            key=key,
            source=source,
            agent=agent,
            rationale=rationale,
            confidence=float(confidence),
        )
        self._provenance[key] = rec
        log.debug("[META] provenance recorded: %s (conf=%.2f, agent=%s)", key, confidence, agent)
        return rec

    def get_confidence_snapshot(self) -> Dict[str, Any]:
        """
        Return a serialisable confidence snapshot for the CLI 'confidence' command.

        The snapshot includes:
          • overall_confidence:    weighted mean across all provenance records.
          • total_tracked:         number of facts with provenance.
          • high / medium / low:   counts per tier.
          • top_sources:           top-5 most-cited sources.
          • recent_entries:        last-10 provenance records (key, conf, source).
          • knowledge_map_summary: from the latest build_knowledge_map().
        """
        records = list(self._provenance.values())
        if not records:
            return {
                "overall_confidence": "0.0%",
                "total_tracked": 0,
                "high": 0, "medium": 0, "low": 0,
                "top_sources": [],
                "recent_entries": [],
                "knowledge_map_summary": self.knowledge_map,
                "note": "No provenance recorded yet — call record_provenance() first.",
            }

        confs = [r.confidence for r in records]
        overall = sum(confs) / len(confs)

        high = [r for r in records if r.confidence >= 0.8]
        med = [r for r in records if 0.5 <= r.confidence < 0.8]
        low = [r for r in records if r.confidence < 0.5]

        # Top-5 sources by occurrence
        source_counts: Dict[str, int] = {}
        for r in records:
            source_counts[r.source] = source_counts.get(r.source, 0) + 1
        top_sources = sorted(source_counts.items(), key=lambda x: -x[1])[:5]

        # Last-10 by timestamp
        recent = sorted(records, key=lambda r: r.ts, reverse=True)[:10]

        return {
            "overall_confidence": f"{overall * 100:.1f}%",
            "total_tracked": len(records),
            "high": len(high),
            "medium": len(med),
            "low": len(low),
            "top_sources": [{"source": s, "count": c} for s, c in top_sources],
            "recent_entries": [
                {
                    "key": r.key[:60],
                    "confidence": round(r.confidence, 3),
                    "source": r.source[:80],
                    "agent": r.agent,
                    "rationale": r.rationale[:120],
                }
                for r in recent
            ],
            "knowledge_map_summary": {
                "total_facts": self.knowledge_map.get("total_facts", 0),
                "high_confidence": len(self.knowledge_map.get("high_confidence", [])),
                "medium_confidence": len(self.knowledge_map.get("medium_confidence", [])),
                "low_confidence": len(self.knowledge_map.get("low_confidence", [])),
                "uncertain": len(self.knowledge_map.get("uncertain", [])),
                "categories": self.knowledge_map.get("categories", {}),
            },
        }

    def get_confidence_parse_tree(self) -> Dict[str, Any]:
        """
        Return a nested confidence parse tree for CLI/API exploration.

        Structure::

            {
              "categories": {
                "<category>": {
                  "high": [ {key, confidence, source, rationale}, … ],
                  "medium": [ … ],
                  "low": [ … ],
                  "tier_summary": {"high": N, "medium": N, "low": N}
                }
              },
              "overall_confidence": "72.3%",
              "total_facts": 120,
            }

        Categories are derived from the knowledge key prefix (the part
        before the first ':'), falling back to "general".
        """
        # Collect all provenance records grouped by category
        cat_tree: Dict[str, Dict[str, List]] = {}

        for r in self._provenance.values():
            cat = r.key.split(":")[0] if ":" in r.key else "general"
            if cat not in cat_tree:
                cat_tree[cat] = {"high": [], "medium": [], "low": []}
            entry = {
                "key": r.key[:80],
                "confidence": round(r.confidence, 3),
                "source": r.source[:80],
                "agent": r.agent,
                "rationale": r.rationale[:120],
            }
            if r.confidence >= 0.8:
                cat_tree[cat]["high"].append(entry)
            elif r.confidence >= 0.5:
                cat_tree[cat]["medium"].append(entry)
            else:
                cat_tree[cat]["low"].append(entry)

        # Add tier summaries per category
        for cat, tiers in cat_tree.items():
            tiers["tier_summary"] = {
                "high": len(tiers["high"]),
                "medium": len(tiers["medium"]),
                "low": len(tiers["low"]),
            }

        # Overall stats
        all_conf = [r.confidence for r in self._provenance.values()]
        overall = f"{sum(all_conf) / max(1, len(all_conf)) * 100:.1f}%"

        return {
            "categories": cat_tree,
            "overall_confidence": overall,
            "total_facts": len(self._provenance),
        }

    def evaluate_understanding_rich(self) -> Dict[str, Any]:
        """
        Extended version of evaluate_understanding() that includes provenance data.

        Original evaluate_understanding() is unchanged; this method adds:
          • top_sources_by_count
          • confidence_breakdown (high/medium/low counts from provenance)
          • rationale_sample (first 3 rationales for high-confidence facts)
        """
        base = self.evaluate_understanding()
        snapshot = self.get_confidence_snapshot()
        base["provenance_summary"] = {
            "total_tracked": snapshot["total_tracked"],
            "high": snapshot["high"],
            "medium": snapshot["medium"],
            "low": snapshot["low"],
            "top_sources": snapshot["top_sources"],
            "rationale_sample": [
                e["rationale"] for e in snapshot["recent_entries"]
                if e.get("confidence", 0) >= 0.8
            ][:3],
        }
        return base

    def confidence_cli_report(self) -> str:
        """
        Return a plain-text confidence report for the CLI 'confidence' command.
        """
        snap = self.get_confidence_snapshot()
        lines = [
            "╔══════════════════════════════════════════════════",
            "║  NIBLIT META-CONFIDENCE SNAPSHOT",
            "╚══════════════════════════════════════════════════",
            f"  Overall confidence:  {snap['overall_confidence']}",
            f"  Total facts tracked: {snap['total_tracked']}",
            f"  High confidence:     {snap['high']}",
            f"  Medium confidence:   {snap['medium']}",
            f"  Low confidence:      {snap['low']}",
            "",
            "  Top sources:",
        ]
        for s in snap["top_sources"]:
            lines.append(f"    • {s['source'][:60]}  ({s['count']} facts)")
        if not snap["top_sources"]:
            lines.append("    (none recorded)")
        lines += [
            "",
            "  Recent high-confidence entries:",
        ]
        shown = 0
        for e in snap["recent_entries"]:
            if e.get("confidence", 0) >= 0.8:
                lines.append(f"    [{e['confidence']:.2f}] {e['key'][:50]}")
                lines.append(f"         src={e['source'][:50]}  agent={e['agent']}")
                shown += 1
                if shown >= 3:
                    break
        if shown == 0:
            lines.append("    (none yet — high-confidence threshold ≥ 0.80)")
        lines += [
            "",
            "  Knowledge map summary:",
            f"    Facts: {snap['knowledge_map_summary']['total_facts']}",
            f"    Categories: {list(snap['knowledge_map_summary']['categories'].keys())[:8]}",
            "══════════════════════════════════════════════════",
        ]
        return "\n".join(lines)
