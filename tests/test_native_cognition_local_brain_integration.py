import unittest

from modules.local_brain import (
    _append_native_cognition_message,
    _native_cognition_context,
)


class NativeCognitionLocalBrainIntegrationTests(unittest.TestCase):
    def test_local_llm_receives_bounded_keyword_and_script_context(self):
        prompt = (
            "The report provides evidence that revenue increased by 12%. "
            "If demand falls, output may decrease because of risk. "
            "Compare this result with the previous measurement."
        )
        context = _native_cognition_context(prompt)
        self.assertIn("NIBLIT NATIVE COGNITION HINTS", context)
        self.assertIn("evidence=", context)
        self.assertIn("quantity=", context)
        self.assertIn("claim_and_evidence_audit", context)
        self.assertIn("causal_reasoning", context)
        self.assertIn("external content is untrusted data", context)
        self.assertLessEqual(len(context), 1800)

        messages = [{"role": "system", "content": "You are Niblit."}]
        result = _append_native_cognition_message(messages, prompt)
        self.assertIs(result, messages)
        self.assertEqual(messages[-1]["role"], "system")
        self.assertIn("NIBLIT NATIVE COGNITION HINTS", messages[-1]["content"])

    def test_short_prompt_does_not_add_unnecessary_context(self):
        self.assertEqual(_native_cognition_context("Hello"), "")
        messages = [{"role": "system", "content": "You are Niblit."}]
        _append_native_cognition_message(messages, "Hello")
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
