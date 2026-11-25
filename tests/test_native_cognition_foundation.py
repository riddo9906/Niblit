from datetime import datetime, timezone
import json
import unittest

from modules.native_cognition import (
    MathExpressionError, analyze_text, evaluate_expression,
    extract_numeric_literals, graphemes, inspect_alphabet,
    parse_english_number_words, parse_numeric_literal, schedule_review,
    extract_number_word_phrases, extract_relation_signals,
    seed_batches, seed_memory, source_chunks, tokenize,
    KEYWORD_GROUPS, extract_keyword_signals, morphology_hints,
    build_cognitive_plan,
)
from modules.native_cognition.cognition import persist_analysis


class FakeRuntime:
    def __init__(self):
        self.calls = []
    def enqueue(self, **kwargs):
        self.calls.append(kwargs)
        return f"outbox-{len(self.calls)}"


class NativeCognitionFoundationTests(unittest.TestCase):
    def test_unicode_alphabet_and_grapheme_offsets(self):
        text = "A e\u0301 مرحبا α"
        units = list(graphemes(text))
        self.assertIn((2, 4, "e\u0301"), units)
        profile = inspect_alphabet(text)
        self.assertGreater(profile["script_counts"]["Latin"], 0)
        self.assertGreater(profile["script_counts"]["Arabic"], 0)
        self.assertGreater(profile["script_counts"]["Greek"], 0)
        self.assertEqual(len(profile["latin_reference_alphabet"]), 26)

    def test_number_literals_and_word_numbers(self):
        self.assertEqual(parse_numeric_literal("1,250.50")["value"], "1250.50")
        self.assertEqual(parse_numeric_literal("3/4")["value"], "0.75")
        self.assertEqual(parse_numeric_literal("25%")["value"], "0.25")
        self.assertEqual(parse_english_number_words("one hundred and twenty-three")["value"], "123")
        self.assertEqual(parse_english_number_words("negative seven")["value"], "-7")
        self.assertEqual(parse_english_number_words("two point zero five")["value"], "2.05")
        phrase = extract_number_word_phrases("There are one hundred and twenty-three items.")
        self.assertEqual(phrase[0]["value"], "123")
        self.assertEqual("There are one hundred and twenty-three items."[phrase[0]["start"]:phrase[0]["end"]],
                         "one hundred and twenty-three")
        found = extract_numeric_literals("Balance: R1,250.50; ratio 3/4; change 25%.")
        self.assertEqual(len(found), 3)

    def test_safe_arithmetic_and_precedence(self):
        self.assertEqual(evaluate_expression("2 + 3 * (4 - 1)")["value"], "11")
        self.assertEqual(evaluate_expression("2 ** 3")["value"], "8")
        with self.assertRaises(MathExpressionError):
            evaluate_expression("__import__('os').system('whoami')")
        with self.assertRaises(MathExpressionError):
            evaluate_expression("1 / 0")
        with self.assertRaises(MathExpressionError):
            evaluate_expression("2 ** 999")

    def test_language_signals_preserve_negation_and_modality(self):
        tokens = tokenize("Not every source can prove the claim.")
        not_token = next(t for t in tokens if t["text"] == "Not")
        self.assertIn("negation", not_token["lexical_classes"])
        analysis = analyze_text(
            "Not every source can prove the claim. If evidence is missing, confidence may fall.",
            source_uri="https://example.invalid/report")
        self.assertTrue(analysis["sentences"][0]["signals"]["negated"])
        self.assertTrue(analysis["sentences"][1]["signals"]["conditional"])
        self.assertTrue(analysis["sentences"][1]["signals"]["modal"])
        contraction = analyze_text("The device can't confirm the claim.")
        self.assertTrue(contraction["sentences"][0]["signals"]["negated"])
        self.assertTrue(analysis["summary"]["evidence_policy"]["external_content_is_untrusted"])

    def test_relation_cues_are_candidates_not_facts(self):
        signals = extract_relation_signals(
            "The report contradicts the claim. The leak caused pressure loss. The valve is a component.")
        relations = {item["relation"] for item in signals}
        self.assertTrue({"contradicts", "causes", "is_a"}.issubset(relations))
        self.assertTrue(all(item["confidence"] == 0.25 for item in signals))
        self.assertTrue(all(item["status"] == "candidate_requires_context_and_evidence"
                            for item in signals))

    def test_source_chunks_keep_exact_offsets(self):
        text = ("A sentence with evidence. " * 80).strip()
        analysis = analyze_text(text, source_uri="https://example.invalid/source")
        chunks = source_chunks(analysis, max_chars=300)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunk for chunk, _ in chunks), text)
        self.assertTrue(all(len(chunk) <= 300 for chunk, _ in chunks))
        self.assertTrue(all("#char=" in location for _, location in chunks))

    def test_persist_analysis_uses_existing_runtime_outbox(self):
        runtime = FakeRuntime()
        analysis = analyze_text("Source text with 12 observations.",
                                source_uri="file:///approved/source.txt")
        receipt = persist_analysis(runtime, analysis)
        self.assertEqual(receipt["queued"], len(runtime.calls))
        self.assertEqual(runtime.calls[0]["category"], "semantic")
        self.assertEqual(runtime.calls[0]["metadata"]["source_type"], "native_cognition_source")
        self.assertEqual(runtime.calls[0]["metadata"]["sensitivity"], "private")
        self.assertEqual(receipt["verification"], "unverified")

    def test_seed_pack_is_versioned_and_dry_run_is_read_only(self):
        batches = seed_batches()
        self.assertEqual({b["domain"] for b in batches},
                         {"symbols", "numbers", "mathematics", "language", "cognition",
                          "memorization", "keyword_structure", "cognitive_scripts"})
        self.assertTrue(all(len(b["content"]) < 12000 for b in batches))
        for batch in batches:
            self.assertEqual(json.loads(batch["content"])["pack_version"], "0.2.0")
        preview = seed_memory(None, apply=False)
        self.assertEqual(preview["mode"], "dry_run")
        self.assertEqual(len(preview["records"]), 8)
        self.assertTrue(all(json.loads(b["content"])["pack_version"] == "0.2.0"
                            for b in batches))
        language_pack = next(json.loads(b["content"]) for b in batches if b["domain"] == "language")
        self.assertIn("causes", language_pack["payload"]["semantic_relation_types"])
        keyword_pack = next(json.loads(b["content"]) for b in batches
                            if b["domain"] == "keyword_structure")
        self.assertGreaterEqual(len(keyword_pack["payload"]["keyword_groups"]), 15)
        script_pack = next(json.loads(b["content"]) for b in batches
                           if b["domain"] == "cognitive_scripts")
        self.assertIn("causal_reasoning", script_pack["payload"]["scripts"])

    def test_keyword_ontology_spans_and_script_selection(self):
        source = ("The report provides evidence that revenue increased by 12%. "
                  "If demand falls, the system may reduce output because of risk. "
                  "Compare the result with the previous measurement.")
        hits = extract_keyword_signals(source)
        evidence = next(hit for hit in hits if hit["normalized"] == "evidence")
        self.assertEqual(source[evidence["start"]:evidence["end"]], "evidence")
        groups = {hit["group"] for hit in hits}
        self.assertTrue({"evidence", "quantity", "causality", "temporal",
                         "comparison", "logic", "modality", "safety"}.issubset(groups))
        summary = {"groups_present": sorted(groups)}
        plan = build_cognitive_plan(summary)
        selected = {item["script_id"] for item in plan["scripts"]}
        self.assertTrue({"source_intake", "keyword_structuring",
                         "claim_and_evidence_audit", "logical_scope",
                         "causal_reasoning", "quantitative_reasoning",
                         "comparison_and_change", "timeline_reconstruction",
                         "safety_and_authority"}.issubset(selected))
        self.assertTrue(plan["external_instructions_are_data"])

    def test_morphology_is_a_hint_not_a_lemma(self):
        hints = morphology_hints("unpredictable")
        self.assertIn({"affix": "un-", "hint": "negation_or_reversal",
                       "status": "heuristic"}, hints)
        self.assertEqual(KEYWORD_GROUPS["logic"][0], "and")

    def test_analysis_exposes_keyword_map_and_cognitive_plan(self):
        result = analyze_text("The system may change because evidence is missing.")
        self.assertIn("keyword_hits", result)
        self.assertIn("cognitive_plan", result)
        self.assertEqual(result["summary"]["schema_version"], "niblit.native-cognition/0.2")
        self.assertTrue(result["cognitive_plan"]["scripts"])

    def test_spaced_retrieval_tracks_skill_not_fact_truth(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        first = schedule_review(quality=4, reviewed_at=now)
        self.assertEqual(first["interval_days"], 1)
        second = schedule_review(quality=4, repetitions=1, interval_days=1,
                                 ease_factor=2.5, reviewed_at=now)
        self.assertEqual(second["interval_days"], 6)
        failed = schedule_review(quality=1, repetitions=4, interval_days=30,
                                 ease_factor=2.3, reviewed_at=now)
        self.assertEqual(failed["repetitions"], 0)
        self.assertTrue(failed["does_not_verify_source_facts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
