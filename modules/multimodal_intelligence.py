#!/usr/bin/env python3
"""
MULTIMODAL INTELLIGENCE MODULE
Unified interface for processing text, structured data, code, and numeric inputs
across multiple modalities — all without requiring external vision/audio APIs.
"""

import logging
import json
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("MultimodalIntelligence")


class ModalityResult:
    """Container for the output of a single modality processor."""

    def __init__(self, modality: str, content: Any, metadata: Optional[Dict] = None):
        self.modality = modality
        self.content = content
        self.metadata: Dict[str, Any] = metadata or {}
        self.confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modality": self.modality,
            "content": self.content,
            "metadata": self.metadata,
            "confidence": self.confidence,
        }


class MultimodalIntelligence:
    """
    Process and reason across multiple input modalities:

    - text       : natural language, summarisation, keyword extraction
    - code       : language detection, structure analysis, complexity hints
    - json/data  : schema inference, key extraction, data description
    - numeric    : basic stats (min/max/mean), trend description
    - mixed      : auto-detect the dominant modality and delegate
    """

    SUPPORTED_MODALITIES = ["text", "code", "json", "numeric", "mixed"]

    def __init__(self, db=None):
        self.db = db
        self._session_inputs: List[Dict[str, Any]] = []
        log.info("[MULTIMODAL] MultimodalIntelligence initialised")

    # ─────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────

    def process(self, content: Any, modality: str = "mixed", context: Optional[str] = None) -> ModalityResult:
        """
        Process content in the specified modality.

        Parameters
        ----------
        content  : the input (str, list of numbers, dict, etc.)
        modality : one of SUPPORTED_MODALITIES (default: auto-detect via 'mixed')
        context  : optional free-text hint about the content's purpose
        """
        if modality == "mixed":
            modality = self._detect_modality(content)

        log.info(f"[MULTIMODAL] Processing modality='{modality}'")

        processors = {
            "text": self._process_text,
            "code": self._process_code,
            "json": self._process_json,
            "numeric": self._process_numeric,
        }

        processor = processors.get(modality, self._process_text)
        result = processor(content, context)

        self._session_inputs.append({"modality": modality, "summary": str(result.content)[:80]})

        if self.db:
            try:
                self.db.add_fact(
                    f"multimodal_{modality}",
                    str(result.content)[:200],
                    tags=["multimodal", modality],
                )
            except Exception:
                pass

        return result

    def describe(self, content: Any, context: Optional[str] = None) -> str:
        """Convenience method: process and return a plain text description."""
        result = self.process(content, modality="mixed", context=context)
        return str(result.content)

    def fuse(self, inputs: List[Dict[str, Any]]) -> str:
        """
        Fuse multiple modality results into a coherent unified description.

        Each element of `inputs` should be {"modality": str, "content": Any}.
        """
        results = [self.process(item["content"], item.get("modality", "mixed")) for item in inputs]
        parts = [f"[{r.modality.upper()}] {r.content}" for r in results]
        fused = " | ".join(parts)
        log.info(f"[MULTIMODAL] Fused {len(results)} modalities")
        return fused

    # ─────────────────────────────────────────────────────
    # Modality processors
    # ─────────────────────────────────────────────────────

    def _process_text(self, content: Any, context: Optional[str] = None) -> ModalityResult:
        text = str(content)
        words = text.split()
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        keywords = self._extract_keywords(text)

        description = (
            f"Text input: {len(words)} words, ~{len(sentences)} sentences. "
            f"Key terms: {', '.join(keywords[:5]) if keywords else 'none'}. "
            f"Preview: {text[:120]}{'…' if len(text) > 120 else ''}"
        )
        return ModalityResult("text", description, {"word_count": len(words), "keywords": keywords[:10]})

    def _process_code(self, content: Any, context: Optional[str] = None) -> ModalityResult:
        code = str(content)
        language = self._detect_code_language(code)
        lines = code.strip().split("\n")
        functions = [l.strip() for l in lines if re.match(r'^\s*(def |function |func |public |private |class )', l)]
        imports = [l.strip() for l in lines if re.match(r'^\s*(import |from |require|use |include)', l)]

        description = (
            f"Code [{language}]: {len(lines)} lines, "
            f"{len(functions)} function/class definition(s), "
            f"{len(imports)} import(s). "
            f"First line: {lines[0][:80] if lines else '(empty)'}"
        )
        return ModalityResult("code", description, {
            "language": language,
            "lines": len(lines),
            "functions": functions[:5],
            "imports": imports[:5],
        })

    def _process_json(self, content: Any, context: Optional[str] = None) -> ModalityResult:
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return ModalityResult("json", f"Invalid JSON: {content[:80]}")
        else:
            data = content

        if isinstance(data, dict):
            keys = list(data.keys())
            description = f"JSON object: {len(keys)} keys — {', '.join(str(k) for k in keys[:8])}"
        elif isinstance(data, list):
            description = f"JSON array: {len(data)} items; first item type: {type(data[0]).__name__ if data else 'n/a'}"
        else:
            description = f"JSON scalar ({type(data).__name__}): {str(data)[:80]}"

        return ModalityResult("json", description, {"type": type(data).__name__})

    def _process_numeric(self, content: Any, context: Optional[str] = None) -> ModalityResult:
        try:
            if isinstance(content, str):
                numbers = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', content)]
            elif isinstance(content, (int, float)):
                numbers = [float(content)]
            else:
                numbers = [float(x) for x in content]
        except (TypeError, ValueError):
            return ModalityResult("numeric", f"Could not parse numeric content: {str(content)[:80]}")

        if not numbers:
            return ModalityResult("numeric", "No numeric values found")

        n = len(numbers)
        total = sum(numbers)
        mean = total / n
        mn = min(numbers)
        mx = max(numbers)
        trend = "increasing" if numbers[-1] > numbers[0] else ("decreasing" if numbers[-1] < numbers[0] else "stable")
        if len(numbers) < 2:
            trend = "N/A (single value)"

        description = (
            f"Numeric data: {n} value(s), "
            f"min={mn:.3g}, max={mx:.3g}, mean={mean:.3g}, "
            f"trend={trend}"
        )
        return ModalityResult("numeric", description, {"count": n, "min": mn, "max": mx, "mean": mean})

    # ─────────────────────────────────────────────────────
    # Auto-detection helpers
    # ─────────────────────────────────────────────────────

    def _detect_modality(self, content: Any) -> str:
        """Heuristically detect the most likely modality."""
        if isinstance(content, (int, float)):
            return "numeric"
        if isinstance(content, (list, tuple)) and all(isinstance(x, (int, float)) for x in content):
            return "numeric"
        if isinstance(content, dict):
            return "json"

        text = str(content).strip()

        # JSON string?
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                json.loads(text)
                return "json"
            except json.JSONDecodeError:
                pass

        # Code heuristic: check for common programming constructs
        code_patterns = [r'\bdef \w+\(', r'\bfunction \w+\(', r'\bimport \w+', r'\bclass \w+[:(]',
                         r'^\s*#.*$', r'^\s*//.*$', r'\bif\s+.+:\s*$', r'\bfor\s+.+in\s+']
        if sum(1 for p in code_patterns if re.search(p, text, re.MULTILINE)) >= 2:
            return "code"

        # Numeric string?
        nums = re.findall(r'-?\d+(?:\.\d+)?', text)
        non_num = re.sub(r'[-\d.,\s]+', '', text)
        if nums and len(non_num) < len(text) * 0.3:
            return "numeric"

        return "text"

    def _detect_code_language(self, code: str) -> str:
        """Detect programming language from code snippet."""
        patterns = {
            "python": [r'\bdef \w+\(', r'\bimport \w+', r'\bprint\s*\(', r':\s*$'],
            "javascript": [r'\bfunction \w+\(', r'\bconst \w+\s*=', r'\blet \w+\s*=', r'=>'],
            "java": [r'\bpublic\s+class\b', r'\bSystem\.out\b', r'\bvoid\s+\w+\('],
            "bash": [r'^#!/bin/bash', r'\becho\s+"', r'\$\(', r'\|\s*grep\b'],
            "sql": [r'\bSELECT\b', r'\bFROM\b', r'\bWHERE\b', r'\bINSERT\b'],
            "html": [r'<html', r'<div', r'<body', r'</\w+>'],
        }
        scores: Dict[str, int] = {}
        for lang, pats in patterns.items():
            scores[lang] = sum(1 for p in pats if re.search(p, code, re.IGNORECASE | re.MULTILINE))
        best = max(scores, key=lambda k: scores[k]) if scores else "unknown"
        return best if scores.get(best, 0) > 0 else "unknown"

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract simple keyword list from text."""
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'shall', 'can', 'and', 'or', 'but', 'in',
            'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'this', 'that',
            'it', 'its', 'not', 'as', 'if', 'so', 'than', 'then', 'they', 'them',
        }
        words = re.findall(r'\b[a-zA-Z][a-zA-Z_\-]{2,}\b', text.lower())
        seen: set = set()
        keywords: List[str] = []
        for w in words:
            if w not in stopwords and w not in seen:
                seen.add(w)
                keywords.append(w)
        return keywords[:20]

    # ─────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return module status overview."""
        modality_counts: Dict[str, int] = {}
        for entry in self._session_inputs:
            m = entry["modality"]
            modality_counts[m] = modality_counts.get(m, 0) + 1

        return {
            "supported_modalities": self.SUPPORTED_MODALITIES,
            "inputs_processed": len(self._session_inputs),
            "modality_breakdown": modality_counts,
            "capability": "Text, code, JSON, and numeric intelligence",
            "status": "Ready",
        }
