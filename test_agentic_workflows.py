"""
test_agentic_workflows.py — Unit tests for modules/agentic_workflows.py.

Run with::

    pytest test_agentic_workflows.py -v

All tests use lightweight lambdas and MagicMock stubs so no heavy services
are required.
"""

import pytest
from unittest.mock import MagicMock

from modules.agentic_workflows import AgenticWorkflow, WorkflowStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(db=None) -> AgenticWorkflow:
    """Return a fresh AgenticWorkflow instance."""
    return AgenticWorkflow(db=db)


def _simple_step(name: str, return_value: str = "ok") -> WorkflowStep:
    """Return a WorkflowStep whose action always returns *return_value*."""
    return WorkflowStep(name, lambda ctx: return_value, description=f"{name} step")


def _failing_step(name: str) -> WorkflowStep:
    """Return a WorkflowStep whose action always raises."""
    def _boom(ctx):
        raise ValueError("intentional failure")
    return WorkflowStep(name, _boom, description="always fails")


# ---------------------------------------------------------------------------
# WorkflowStep
# ---------------------------------------------------------------------------

class TestWorkflowStep:
    def test_initial_status_is_pending(self):
        step = _simple_step("init")
        assert step.status == "pending"

    def test_run_sets_status_done_on_success(self):
        step = _simple_step("compute")
        step.run({})
        assert step.status == "done"

    def test_run_returns_action_result(self):
        step = _simple_step("compute", return_value="hello")
        result = step.run({})
        assert result == "hello"

    def test_run_stores_result_attribute(self):
        step = _simple_step("compute", return_value="stored")
        step.run({})
        assert step.result == "stored"

    def test_run_passes_context_to_action(self):
        received = {}

        def _capture(ctx):
            received.update(ctx)
            return "captured"

        step = WorkflowStep("capture", _capture)
        step.run({"key": "value"})
        assert received.get("key") == "value"

    def test_failing_action_sets_status_failed(self):
        step = _failing_step("bad")
        step.run({})
        assert step.status == "failed"

    def test_failing_action_returns_error_string(self):
        step = _failing_step("bad")
        result = step.run({})
        assert isinstance(result, str)
        assert "[ERROR]" in result

    def test_description_stored(self):
        step = WorkflowStep("named", lambda ctx: None, description="my desc")
        assert step.description == "my desc"


# ---------------------------------------------------------------------------
# AgenticWorkflow construction
# ---------------------------------------------------------------------------

class TestAgenticWorkflowConstruction:
    def test_creates_without_arguments(self):
        wf = AgenticWorkflow()
        assert wf is not None

    def test_creates_with_db(self):
        mock_db = MagicMock()
        wf = AgenticWorkflow(db=mock_db)
        assert wf.db is mock_db

    def test_built_in_workflows_registered(self):
        wf = _make_workflow()
        names = wf.list_workflows()
        assert "research_and_summarise" in names
        assert "goal_decomposition" in names
        assert "self_improvement_cycle" in names

    def test_history_empty_on_init(self):
        wf = _make_workflow()
        assert wf.history == []


# ---------------------------------------------------------------------------
# register_workflow
# ---------------------------------------------------------------------------

class TestRegisterWorkflow:
    def test_register_custom_workflow(self):
        wf = _make_workflow()
        wf.register_workflow("custom", [_simple_step("step1")])
        assert "custom" in wf.list_workflows()

    def test_registered_workflow_can_be_run(self):
        wf = _make_workflow()
        wf.register_workflow("demo", [_simple_step("only")])
        result = wf.run_workflow("demo")
        assert result["status"] == "done"

    def test_register_overwrites_existing(self):
        wf = _make_workflow()
        wf.register_workflow("dup", [_simple_step("a")])
        wf.register_workflow("dup", [_simple_step("b"), _simple_step("c")])
        result = wf.run_workflow("dup")
        assert len(result["steps"]) == 2


# ---------------------------------------------------------------------------
# run_workflow
# ---------------------------------------------------------------------------

class TestRunWorkflow:
    def test_unknown_workflow_returns_error_key(self):
        wf = _make_workflow()
        result = wf.run_workflow("nonexistent")
        assert "error" in result

    def test_unknown_workflow_lists_available(self):
        wf = _make_workflow()
        result = wf.run_workflow("nonexistent")
        assert "available" in result
        assert isinstance(result["available"], list)

    def test_run_returns_required_keys(self):
        wf = _make_workflow()
        result = wf.run_workflow("research_and_summarise", {"topic": "AI"})
        for key in ("workflow", "steps", "context", "status"):
            assert key in result

    def test_run_workflow_name_in_result(self):
        wf = _make_workflow()
        result = wf.run_workflow("research_and_summarise", {"topic": "AI"})
        assert result["workflow"] == "research_and_summarise"

    def test_run_goal_decomposition(self):
        wf = _make_workflow()
        result = wf.run_workflow("goal_decomposition", {"goal": "learn Python"})
        assert result["status"] in ("done", "completed_with_failures")

    def test_run_self_improvement_cycle(self):
        wf = _make_workflow()
        result = wf.run_workflow("self_improvement_cycle")
        assert result["status"] in ("done", "completed_with_failures")

    def test_successful_steps_have_done_status(self):
        wf = _make_workflow()
        wf.register_workflow("all_pass", [_simple_step("s1"), _simple_step("s2")])
        result = wf.run_workflow("all_pass")
        for step in result["steps"]:
            assert step["status"] == "done"

    def test_failed_step_marks_overall_as_completed_with_failures(self):
        wf = _make_workflow()
        wf.register_workflow("has_fail", [_simple_step("ok"), _failing_step("bad")])
        result = wf.run_workflow("has_fail")
        assert result["status"] == "completed_with_failures"

    def test_context_propagates_between_steps(self):
        wf = _make_workflow()
        step_a = WorkflowStep("step_a", lambda ctx: "value_from_a")
        step_b = WorkflowStep("step_b", lambda ctx: ctx.get("step_a", "missing"))
        wf.register_workflow("chain", [step_a, step_b])
        result = wf.run_workflow("chain")
        assert result["context"]["step_b"] == "value_from_a"

    def test_initial_context_available_to_first_step(self):
        wf = _make_workflow()
        received = {}

        def _grab(ctx):
            received.update(ctx)
            return "done"

        wf.register_workflow("ctx_test", [WorkflowStep("grab", _grab)])
        wf.run_workflow("ctx_test", {"seed": "hello"})
        assert received.get("seed") == "hello"

    def test_run_appends_to_history(self):
        wf = _make_workflow()
        wf.run_workflow("research_and_summarise", {"topic": "AI"})
        assert len(wf.history) == 1

    def test_run_stores_to_db_when_provided(self):
        mock_db = MagicMock()
        wf = _make_workflow(db=mock_db)
        wf.run_workflow("research_and_summarise", {"topic": "AI"})
        mock_db.add_fact.assert_called_once()

    def test_run_no_db_does_not_raise(self):
        wf = _make_workflow(db=None)
        result = wf.run_workflow("research_and_summarise", {"topic": "AI"})
        assert "error" not in result

    def test_empty_workflow_completes(self):
        wf = _make_workflow()
        wf.register_workflow("empty", [])
        result = wf.run_workflow("empty")
        assert result["status"] == "done"
        assert result["steps"] == []


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------

class TestListWorkflows:
    def test_returns_list(self):
        wf = _make_workflow()
        assert isinstance(wf.list_workflows(), list)

    def test_contains_built_in_workflows(self):
        wf = _make_workflow()
        names = wf.list_workflows()
        assert "research_and_summarise" in names

    def test_includes_custom_workflow_after_registration(self):
        wf = _make_workflow()
        wf.register_workflow("my_workflow", [_simple_step("x")])
        assert "my_workflow" in wf.list_workflows()


# ---------------------------------------------------------------------------
# workflow_status
# ---------------------------------------------------------------------------

class TestWorkflowStatus:
    def test_status_has_required_keys(self):
        wf = _make_workflow()
        status = wf.workflow_status()
        for key in ("registered_workflows", "workflows", "built_in",
                    "executions_this_session", "last_run", "capability", "status"):
            assert key in status

    def test_status_registered_count_matches_list(self):
        wf = _make_workflow()
        status = wf.workflow_status()
        assert status["registered_workflows"] == len(wf.list_workflows())

    def test_executions_increments_after_run(self):
        wf = _make_workflow()
        assert wf.workflow_status()["executions_this_session"] == 0
        wf.run_workflow("research_and_summarise", {"topic": "test"})
        assert wf.workflow_status()["executions_this_session"] == 1

    def test_last_run_updates_after_workflow(self):
        wf = _make_workflow()
        assert wf.workflow_status()["last_run"] is None
        wf.run_workflow("goal_decomposition", {"goal": "something"})
        assert wf.workflow_status()["last_run"] == "goal_decomposition"


# ---------------------------------------------------------------------------
# format_result
# ---------------------------------------------------------------------------

class TestFormatResult:
    def test_format_valid_result(self):
        wf = _make_workflow()
        result = wf.run_workflow("research_and_summarise", {"topic": "testing"})
        text = wf.format_result(result)
        assert isinstance(text, str)
        assert "AGENTIC WORKFLOW" in text

    def test_format_error_result(self):
        wf = _make_workflow()
        error_result = {"error": "not found", "available": ["wf1"]}
        text = wf.format_result(error_result)
        assert "error" in text.lower()

    def test_format_includes_step_results(self):
        wf = _make_workflow()
        wf.register_workflow("fmt_test", [_simple_step("only_step", "my_output")])
        result = wf.run_workflow("fmt_test")
        text = wf.format_result(result)
        assert "only_step" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
