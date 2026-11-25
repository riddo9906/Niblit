import json
import unittest
from unittest.mock import patch

from modules.research_contracts import ResearchPlan, TopicAssessment
from modules.research_orchestrator import ResearchOrchestrator


class FakeSearch:
    def search(self, query, max_results=3):
        return {"results": [{
            "url": "https://example.invalid/annual-report",
            "domain": "example.invalid",
            "title": "Annual Report",
            "provider": "test",
        }]}


class FakeLoop:
    def __init__(self):
        self.messages = None
    def chat(self, messages):
        self.messages = messages
        return {"text": json.dumps({
            "relevant": True,
            "supports_claims": ["Revenue increased by 12%."],
            "unsupported_claims": [],
            "contradictions": [],
            "confidence": 0.7,
            "requires_followup": False,
            "followup_questions": [],
        })}


class NativeCognitionResearchIntegrationTests(unittest.TestCase):
    def test_external_research_is_structured_before_llm_audit(self):
        loop = FakeLoop()
        orchestrator = ResearchOrchestrator(loop=loop, search=FakeSearch(),
                                            max_searches=1, max_fetches=1)
        plan = ResearchPlan(
            topic_assessment=TopicAssessment("annual report", "annual report"),
            max_searches=1, max_fetches=1, max_rounds=1)
        source_text = (
            "Revenue increased by 12% in the reporting period. "
            "The company did not confirm that the increase will continue. "
            "If demand falls, future revenue may decline. "
            "The report contradicts the earlier estimate. "
            "The warehouse holds one hundred and twenty-three parts."
        )
        with patch("modules.research_orchestrator.governed_fetch",
                   return_value={"evidence": {"extracted_text": source_text}}):
            items = orchestrator._gather(plan, ["annual report"])
        self.assertEqual(len(items), 1)
        item = items[0]
        native = item.native_cognition
        self.assertEqual(native["schema_version"], "niblit.native-cognition/0.2")
        self.assertIn("keyword_signals", native)
        self.assertIn("cognitive_plan", native)
        self.assertGreater(native["keyword_signals"]["hit_count"], 0)
        self.assertGreater(native["token_count"], 0)
        self.assertEqual(native["numeric_literals"][0]["value"], "0.12")
        self.assertEqual(native["numeric_literals"][0]["raw"], "12%")
        self.assertTrue(any(row["signals"]["negated"] for row in native["sentence_signals"]))
        self.assertTrue(any(row["signals"]["conditional"] for row in native["sentence_signals"]))
        self.assertTrue(native["evidence_policy"]["external_content_is_untrusted"])
        self.assertTrue(any(item["relation"] == "contradicts" for item in native["relation_signals"]))
        self.assertEqual(native["number_word_candidates"][0]["value"], "123")

        audit = orchestrator.audit_evidence(item, "What changed?")
        self.assertEqual(audit.audit_status, "pass")
        payload = json.loads(loop.messages[1]["content"])
        self.assertIn("native_cognition", payload["evidence"])
        self.assertIn("heuristic structure only", orchestrator.__class__.__module__ and
                      __import__("modules.research_orchestrator", fromlist=["AUDIT_SYSTEM_PROMPT"]).AUDIT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
