#!/usr/bin/env python3
"""Governed PDF document cognition integrated with runtime/router/memory authority."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.cognitive_episode import RuntimeSignificanceEngine

log = logging.getLogger("GovernedDocumentCognition")

_COLLECTOR: GovernedDocumentCognition | None = None
_LOCK = threading.Lock()
_ROUND_PRECISION = 4
_MAX_CHUNKS = 80
_OCR_MIN_TOTAL_CHARS = 120
_OCR_MIN_CHARS_PER_PAGE = 40


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ExtractedDocument:
    text: str
    pages: int
    backend: str
    needs_ocr: bool
    error: str = ""


class GovernedDocumentCognition:
    """Discover, reason over, and persist governed cognition from local PDFs."""

    def __init__(
        self,
        *,
        checkpoint_path: Path | None = None,
        approved_roots: list[str] | None = None,
    ) -> None:
        from niblit_core.config.paths import get_data_dir

        self._lock = threading.RLock()
        self._significance_engine = RuntimeSignificanceEngine()
        self._checkpoint_path = checkpoint_path or (get_data_dir() / "document_cognition_checkpoint.json")
        roots = approved_roots or [
            item.strip()
            for item in str(os.getenv("NIBLIT_DOCUMENT_APPROVED_ROOTS", "/home")).split(":")
            if item.strip()
        ]
        self._approved_roots = [Path(root).resolve() for root in roots]
        self._state: dict[str, Any] = {
            "documents": {},
            "failures": {},
            "lineage": {},
            "semantic_hashes": [],
            "last_run": {},
        }
        self._last_result: dict[str, Any] = {}
        self._load_checkpoint()

    def ingest_directory(
        self,
        *,
        directory: str = "/home",
        recursive: bool = True,
        max_documents: int = 25,
        router: Any | None = None,
        knowledge_db: Any | None = None,
        evaluation_engine: Any | None = None,
        runtime_id: str = "",
        source_module: str = "governed_document_cognition",
    ) -> dict[str, Any]:
        root = Path(directory).expanduser().resolve()
        if not self._is_approved(root):
            return {
                "success": False,
                "error": f"directory_not_approved:{root}",
                "approved_roots": [str(p) for p in self._approved_roots],
            }

        discovered = self._discover_pdfs(root, recursive=recursive)
        discovered = discovered[: max(1, int(max_documents))]
        ingested: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped: list[str] = []
        dataset_candidates_total = 0

        semantic_hashes: set[str] = set(self._state.get("semantic_hashes", []))

        for pdf_path in discovered:
            doc_key = str(pdf_path)
            fingerprint = self._fingerprint(pdf_path)
            previous = dict(self._state.get("documents", {}).get(doc_key, {}) or {})
            if previous.get("fingerprint") == fingerprint and previous.get("status") == "ingested":
                skipped.append(doc_key)
                continue

            trace_id = uuid.uuid4().hex[:16]
            cognition_id = f"doc-{trace_id[:10]}"
            start = time.time()
            self._emit(
                "document.ingestion.started",
                source=source_module,
                payload={
                    "trace_id": trace_id,
                    "runtime_id": runtime_id,
                    "cognition_id": cognition_id,
                    "document_path": doc_key,
                    "event_category": "ingestion",
                    "event_priority": "high",
                },
            )

            extracted = self._extract_pdf(pdf_path)
            if extracted.error:
                fail_record = {
                    "document_path": doc_key,
                    "fingerprint": fingerprint,
                    "error": extracted.error,
                    "needs_ocr": extracted.needs_ocr,
                }
                failed.append(fail_record)
                self._state.setdefault("failures", {})[doc_key] = {
                    "error": extracted.error,
                    "failed_at": _iso_now(),
                    "fail_count": int(previous.get("fail_count", 0)) + 1,
                    "fingerprint": fingerprint,
                }
                self._emit(
                    "document.ingestion.failed",
                    source=source_module,
                    payload={
                        "trace_id": trace_id,
                        "runtime_id": runtime_id,
                        "cognition_id": cognition_id,
                        "document_path": doc_key,
                        "error": extracted.error,
                        "ocr_required": extracted.needs_ocr,
                        "event_category": "ingestion",
                        "event_priority": "high",
                    },
                )
                continue

            normalized = self._normalize_text(extracted.text)
            chunks = self._chunk_text(normalized)
            topic = self._classify_topic(pdf_path.name, chunks)
            relationships = self._relationships(pdf_path, topic, chunks)
            novelty_score = self._novelty_score(chunks, semantic_hashes)
            synthesis = self._synthesize(
                router=router,
                topic=topic,
                doc_path=doc_key,
                chunks=chunks,
            )
            reflection = self._reflect(
                router=router,
                topic=topic,
                synthesis=synthesis,
                chunks=chunks,
            )
            evaluation_score = self._evaluate(
                evaluation_engine=evaluation_engine,
                topic=topic,
                synthesis=synthesis,
                reflection=reflection,
            )
            significance = self._significance_engine.score_event(
                "document.ingestion.completed",
                source_module,
                {
                    "topic": topic,
                    "summary": synthesis[:280],
                    "event_category": "cognition",
                    "event_priority": "high",
                    "status": "ingested",
                },
            )
            memory_worthiness = max(
                float(significance.get("memory_worthiness_score", 0.0)),
                round((evaluation_score * 0.6) + (novelty_score * 0.4), _ROUND_PRECISION),
            )
            importance = max(0.1, min(1.0, (memory_worthiness + novelty_score + evaluation_score) / 3.0))
            duplicate_semantic = novelty_score < 0.2
            dataset_candidates = self._dataset_candidates(
                topic=topic,
                synthesis=synthesis,
                reflection=reflection,
                score=evaluation_score,
                trace_id=trace_id,
            )
            dataset_candidates_total += len(dataset_candidates)

            memory_id = ""
            try:
                from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

                cluster = get_governed_qdrant_memory_cluster()
                write = cluster.write_memory(
                    synthesis or reflection or topic,
                    memory_type="semantic_memory",
                    payload={
                        "summary": synthesis[:260],
                        "reflection_summary": reflection[:260],
                        "importance_score": importance,
                        "coherence_score": evaluation_score,
                        "advisor_lineage": ["runtime_router_v2", "local_brain", source_module],
                        "causal_chain": [topic, doc_key],
                        "replay_metadata": {
                            "trace_id": trace_id,
                            "decision_lineage": ["pdf_discovery", "pdf_chunking", "router_v2_synthesis"],
                            "causal_references": [doc_key],
                        },
                        "telemetry": {
                            "trace_id": trace_id,
                            "runtime_id": runtime_id,
                            "cognition_id": cognition_id,
                            "source_module": source_module,
                        },
                    },
                )
                memory_id = str(write.get("memory_id", ""))
            except Exception as exc:
                log.debug("governed memory write skipped: %s", exc)

            if knowledge_db is not None and hasattr(knowledge_db, "add_fact"):
                try:
                    knowledge_db.add_fact(
                        f"document_ingestion:{pdf_path.stem}:{int(time.time())}",
                        {
                            "path": doc_key,
                            "topic": topic,
                            "summary": synthesis[:500],
                            "reflection": reflection[:500],
                            "relationships": relationships,
                            "trace_id": trace_id,
                            "memory_worthiness_score": memory_worthiness,
                            "novelty_score": novelty_score,
                            "evaluation_score": evaluation_score,
                            "needs_ocr": extracted.needs_ocr,
                            "duplicate_semantic": duplicate_semantic,
                        },
                        tags=["document_cognition", "pdf", "governed_memory", topic],
                    )
                except Exception:
                    pass

            elapsed_ms = int((time.time() - start) * 1000)
            doc_result = {
                "document_path": doc_key,
                "topic": topic,
                "chunks": len(chunks),
                "relationships": relationships,
                "needs_ocr": extracted.needs_ocr,
                "ocr_backend": extracted.backend,
                "memory_worthiness_score": round(memory_worthiness, _ROUND_PRECISION),
                "novelty_score": round(novelty_score, _ROUND_PRECISION),
                "evaluation_score": round(evaluation_score, _ROUND_PRECISION),
                "importance_score": round(importance, _ROUND_PRECISION),
                "duplicate_semantic": duplicate_semantic,
                "memory_id": memory_id,
                "trace_id": trace_id,
                "dataset_candidates": dataset_candidates,
                "elapsed_ms": elapsed_ms,
            }
            ingested.append(doc_result)
            self._update_document_state(
                doc_key=doc_key,
                fingerprint=fingerprint,
                topic=topic,
                trace_id=trace_id,
                chunks=len(chunks),
                needs_ocr=extracted.needs_ocr,
                status="ingested",
            )
            self._emit(
                "memory.synthesis.created",
                source=source_module,
                payload={
                    "trace_id": trace_id,
                    "runtime_id": runtime_id,
                    "cognition_id": cognition_id,
                    "document_path": doc_key,
                    "summary": synthesis[:280],
                    "reflection_summary": reflection[:280],
                    "evaluation_score": evaluation_score,
                    "novelty_score": novelty_score,
                    "memory_worthiness_score": memory_worthiness,
                    "memory_id": memory_id,
                    "event_category": "memory",
                    "event_priority": "high",
                },
            )
            self._emit(
                "document.ingestion.completed",
                source=source_module,
                payload={
                    "trace_id": trace_id,
                    "runtime_id": runtime_id,
                    "cognition_id": cognition_id,
                    "document_path": doc_key,
                    "topic": topic,
                    "summary": synthesis[:280],
                    "reflection_summary": reflection[:280],
                    "evaluation_score": evaluation_score,
                    "memory_id": memory_id,
                    "event_category": "ingestion",
                    "event_priority": "high",
                    "telemetry": {"elapsed_ms": elapsed_ms, "chunks": len(chunks)},
                },
            )

        compression = {}
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            compression = get_governed_qdrant_memory_cluster().compression_candidates()
        except Exception:
            compression = {}

        result = {
            "success": True,
            "directory": str(root),
            "discovered": len(discovered),
            "ingested": len(ingested),
            "skipped_unchanged": len(skipped),
            "failed": len(failed),
            "documents": ingested,
            "failures": failed,
            "dataset_candidates": dataset_candidates_total,
            "compression_advisory": compression,
            "checkpoint_path": str(self._checkpoint_path),
            "timestamp": _iso_now(),
        }
        with self._lock:
            self._state["semantic_hashes"] = sorted(list(semantic_hashes))[-2000:]
            self._state["last_run"] = {
                "directory": str(root),
                "result": {k: v for k, v in result.items() if k != "documents"},
                "timestamp": _iso_now(),
            }
            self._last_result = dict(result)
            self._save_checkpoint()

        self._emit(
            "document.ingestion.batch.completed",
            source=source_module,
            payload={
                "trace_id": f"doc-batch-{int(time.time())}",
                "runtime_id": runtime_id,
                "summary": f"discovered={len(discovered)} ingested={len(ingested)} failed={len(failed)}",
                "event_category": "ingestion",
                "event_priority": "high",
            },
        )
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "approved_roots": [str(path) for path in self._approved_roots],
                "checkpoint_path": str(self._checkpoint_path),
                "tracked_documents": len(self._state.get("documents", {})),
                "tracked_failures": len(self._state.get("failures", {})),
                "last_run": dict(self._state.get("last_run", {})),
                "last_result": dict(self._last_result),
            }

    def _discover_pdfs(self, root: Path, *, recursive: bool) -> list[Path]:
        if not root.exists():
            return []
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted(path for path in root.glob(pattern) if path.is_file())

    @staticmethod
    def _fingerprint(path: Path) -> str:
        st = path.stat()
        raw = f"{path}:{st.st_size}:{st.st_mtime_ns}"
        return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]

    def _extract_pdf(self, path: Path) -> ExtractedDocument:
        text = ""
        pages = 0
        if not path.exists():
            return ExtractedDocument(text="", pages=0, backend="none", needs_ocr=True, error="file_missing")
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                pages = len(pdf.pages)
                text = "\n".join((page.extract_text() or "") for page in pdf.pages)
            needs_ocr = (len(text.strip()) < _OCR_MIN_TOTAL_CHARS) or (
                pages > 0 and (len(text.strip()) / max(1, pages)) < _OCR_MIN_CHARS_PER_PAGE
            )
            return ExtractedDocument(text=text, pages=pages, backend="pdfplumber", needs_ocr=needs_ocr)
        except Exception:
            pass
        try:
            import PyPDF2

            with open(path, "rb") as fh:
                reader = PyPDF2.PdfReader(fh)
                pages = len(reader.pages)
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            needs_ocr = (len(text.strip()) < _OCR_MIN_TOTAL_CHARS) or (
                pages > 0 and (len(text.strip()) / max(1, pages)) < _OCR_MIN_CHARS_PER_PAGE
            )
            return ExtractedDocument(text=text, pages=pages, backend="pypdf2", needs_ocr=needs_ocr)
        except Exception as exc:
            return ExtractedDocument(
                text="",
                pages=0,
                backend="none",
                needs_ocr=True,
                error=f"extraction_failed:{exc}",
            )

    @staticmethod
    def _normalize_text(text: str) -> str:
        cleaned = text.replace("\x00", " ")
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _chunk_text(text: str, *, target_chars: int = 900, overlap_chars: int = 120) -> list[str]:
        if not text:
            return []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        cursor = ""
        for paragraph in paragraphs:
            if len(cursor) + len(paragraph) + 2 <= target_chars:
                cursor = f"{cursor}\n\n{paragraph}".strip()
                continue
            if cursor:
                chunks.append(cursor)
            if len(paragraph) <= target_chars:
                cursor = paragraph
                continue
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + target_chars)
                chunks.append(paragraph[start:end])
                start = max(end - overlap_chars, start + 1)
            cursor = ""
        if cursor:
            chunks.append(cursor)
        return chunks[:_MAX_CHUNKS]

    @staticmethod
    def _classify_topic(filename: str, chunks: list[str]) -> str:
        corpus = f"{filename} " + " ".join(chunks[:4]).lower()
        labels = {
            "security": ("security", "threat", "vulnerability", "encryption"),
            "finance": ("finance", "market", "trade", "investment", "stock", "crypto"),
            "ai_ml": ("model", "llm", "neural", "learning", "inference", "dataset"),
            "systems": ("kernel", "runtime", "compiler", "distributed", "orchestration"),
            "governance": ("policy", "governance", "compliance", "audit", "contract"),
        }
        for label, terms in labels.items():
            if any(term in corpus for term in terms):
                return label
        return "general_research"

    @staticmethod
    def _relationships(path: Path, topic: str, chunks: list[str]) -> list[dict[str, str]]:
        rels = [
            {"type": "document_topic", "source": path.name, "target": topic},
            {"type": "document_directory", "source": path.name, "target": path.parent.name or str(path.parent)},
        ]
        joined = " ".join(chunks[:3]).lower()
        for token in ("router", "localbrain", "eventbus", "runtime", "memory", "qdrant", "knowledgedb"):
            if token in joined:
                rels.append({"type": "concept_link", "source": path.name, "target": token})
        return rels[:10]

    @staticmethod
    def _dataset_candidates(
        *,
        topic: str,
        synthesis: str,
        reflection: str,
        score: float,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if synthesis:
            out.append(
                {
                    "prompt": f"Summarize knowledge for topic {topic}",
                    "response": synthesis[:1000],
                    "candidate_type": "sft",
                    "trace_id": trace_id,
                    "score": round(score, 4),
                }
            )
        if reflection:
            out.append(
                {
                    "prompt": f"Generate governance reflection for {topic}",
                    "response": reflection[:1000],
                    "candidate_type": "lora_reflection",
                    "trace_id": trace_id,
                    "score": round(max(0.3, score), 4),
                }
            )
        return out

    @staticmethod
    def _evaluate(
        *,
        evaluation_engine: Any | None,
        topic: str,
        synthesis: str,
        reflection: str,
    ) -> float:
        if evaluation_engine is not None and hasattr(evaluation_engine, "score_outcome"):
            try:
                rec = evaluation_engine.score_outcome(
                    user_input=f"document cognition: {topic}",
                    response=synthesis or reflection,
                    decision_result=None,
                )
                return float(getattr(rec, "quality_score", 0.0) or 0.0)
            except Exception:
                pass
        text = synthesis or reflection
        density = min(1.0, len(text.split()) / 120.0) if text else 0.0
        return round(max(0.1, density), _ROUND_PRECISION)

    @staticmethod
    def _synthesize(*, router: Any | None, topic: str, doc_path: str, chunks: list[str]) -> str:
        if not chunks:
            return ""
        evidence = "\n".join(f"- {chunk[:420]}" for chunk in chunks[:6])
        if router is not None and hasattr(router, "generate"):
            prompt = (
                "You are Niblit's governed document cognition layer.\n"
                "Synthesize key knowledge, uncertainty, and actionable memory from the PDF evidence.\n"
                "No autonomous actions. No invented citations.\n\n"
                f"Document: {doc_path}\n"
                f"Topic guess: {topic}\n"
                f"Evidence:\n{evidence[:3600]}"
            )
            try:
                text = str(router.generate(prompt=prompt, context="governed_document_cognition") or "").strip()
                if text:
                    return text
            except Exception as exc:
                log.debug("document synthesis failed: %s", exc)
        return chunks[0][:900]

    @staticmethod
    def _reflect(*, router: Any | None, topic: str, synthesis: str, chunks: list[str]) -> str:
        base = synthesis or (chunks[0] if chunks else "")
        if not base:
            return ""
        if router is not None and hasattr(router, "generate"):
            prompt = (
                "Generate a short governed reflection for document cognition.\n"
                "Include certainty level, likely gaps, and verification needs.\n"
                f"Topic: {topic}\n"
                f"Synthesis: {base[:2000]}"
            )
            try:
                text = str(router.generate(prompt=prompt, context="governed_document_reflection") or "").strip()
                if text:
                    return text
            except Exception as exc:
                log.debug("document reflection failed: %s", exc)
        return f"Reflection for {topic}: requires follow-up verification on extraction fidelity."

    @staticmethod
    def _novelty_score(chunks: list[str], semantic_hashes: set[str]) -> float:
        if not chunks:
            return 0.0
        hashes = []
        new_items = 0
        for chunk in chunks[:20]:
            digest = hashlib.sha1(chunk.lower().encode("utf-8", errors="replace")).hexdigest()[:16]
            hashes.append(digest)
            if digest not in semantic_hashes:
                new_items += 1
        semantic_hashes.update(hashes)
        return round(new_items / max(1, len(hashes)), _ROUND_PRECISION)

    def _is_approved(self, target: Path) -> bool:
        resolved = target.resolve()
        return any(str(resolved).startswith(str(root)) for root in self._approved_roots)

    def _update_document_state(
        self,
        *,
        doc_key: str,
        fingerprint: str,
        topic: str,
        trace_id: str,
        chunks: int,
        needs_ocr: bool,
        status: str,
    ) -> None:
        with self._lock:
            existing = dict(self._state.get("documents", {}).get(doc_key, {}) or {})
            history = list(self._state.setdefault("lineage", {}).get(doc_key, []))
            if existing.get("fingerprint") and existing.get("fingerprint") != fingerprint:
                history.append(existing.get("fingerprint"))
            self._state.setdefault("lineage", {})[doc_key] = history[-20:]
            self._state.setdefault("documents", {})[doc_key] = {
                "fingerprint": fingerprint,
                "topic": topic,
                "trace_id": trace_id,
                "status": status,
                "chunks": chunks,
                "needs_ocr": needs_ocr,
                "last_ingested_at": _iso_now(),
                "fail_count": 0,
            }
            self._state.get("failures", {}).pop(doc_key, None)

    def _load_checkpoint(self) -> None:
        try:
            if not self._checkpoint_path.exists():
                return
            raw = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state.update(raw)
        except Exception as exc:
            log.debug("document checkpoint load failed: %s", exc)

    def _save_checkpoint(self) -> None:
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._checkpoint_path.with_suffix(self._checkpoint_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._checkpoint_path)

    @staticmethod
    def _emit(event_type: str, *, source: str, payload: dict[str, Any]) -> None:
        try:
            from modules.event_bus import NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(type=event_type, source=source, payload=dict(payload))
            )
        except Exception:
            pass
        try:
            from modules.unified_runtime import get_unified_runtime

            get_unified_runtime().ingest_external_event(
                event_type=event_type,
                source=source,
                payload=dict(payload),
            )
        except Exception:
            pass


def get_governed_document_cognition() -> GovernedDocumentCognition:
    global _COLLECTOR
    with _LOCK:
        if _COLLECTOR is None:
            _COLLECTOR = GovernedDocumentCognition()
    return _COLLECTOR
