#!/usr/bin/env python3
"""
AGENTIC WORKFLOWS MODULE
Multi-step autonomous task pipelines with tool use, planning, and execution
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("AgenticWorkflows")


class WorkflowStep:
    """A single step in an agentic workflow."""

    def __init__(self, name: str, action: Callable, description: str = ""):
        self.name = name
        self.action = action
        self.description = description
        self.result: Optional[Any] = None
        self.status: str = "pending"  # pending | running | done | failed

    def run(self, context: Dict[str, Any]) -> Any:
        self.status = "running"
        try:
            self.result = self.action(context)
            self.status = "done"
        except Exception as e:
            self.result = f"[ERROR] {e}"
            self.status = "failed"
            log.warning(f"[AGENTIC] Step '{self.name}' failed: {e}")
        return self.result


class AgenticWorkflow:
    """
    Execute multi-step agentic task pipelines.

    Each workflow is a named sequence of WorkflowSteps that share a
    mutable context dict.  Results from earlier steps are available to
    later steps via that context.
    """

    def __init__(self, db=None):
        self.db = db
        self.workflows: Dict[str, List[WorkflowStep]] = {}
        self.history: List[Dict[str, Any]] = []
        self._built_in_workflows: List[str] = []
        self._register_built_in_workflows()

    # ─────────────────────────────────────────────────────
    # Built-in workflows
    # ─────────────────────────────────────────────────────

    def _register_built_in_workflows(self) -> None:
        """Register default agentic pipelines."""
        self.register_workflow("research_and_summarise", [
            WorkflowStep("plan", lambda ctx: f"Planning research on: {ctx.get('topic', 'unknown')}", "Plan the research"),
            WorkflowStep("gather", lambda ctx: f"Gathering data for: {ctx.get('topic', 'unknown')}", "Gather raw data"),
            WorkflowStep("analyse", lambda ctx: f"Analysing gathered data: {ctx.get('gather', '')[:80]}", "Analyse data"),
            WorkflowStep("summarise", lambda ctx: f"Summary of '{ctx.get('topic', 'unknown')}': {ctx.get('analyse', '')[:120]}", "Produce summary"),
        ])

        self.register_workflow("goal_decomposition", [
            WorkflowStep("understand_goal", lambda ctx: f"Goal understood: {ctx.get('goal', 'unknown')}", "Understand the goal"),
            WorkflowStep("break_down", lambda ctx: f"Sub-tasks: [1] Research, [2] Plan, [3] Execute for '{ctx.get('goal', '')}'", "Decompose goal"),
            WorkflowStep("prioritise", lambda ctx: f"Priority order established for: {ctx.get('break_down', '')[:80]}", "Prioritise sub-tasks"),
            WorkflowStep("execute_plan", lambda ctx: f"Executing plan: {ctx.get('prioritise', '')[:80]}", "Execute"),
        ])

        self.register_workflow("self_improvement_cycle", [
            WorkflowStep("identify_gaps", lambda ctx: "Identifying knowledge and capability gaps", "Find gaps"),
            WorkflowStep("research_gaps", lambda ctx: f"Researching solutions for gaps: {ctx.get('identify_gaps', '')[:60]}", "Research"),
            WorkflowStep("implement_fixes", lambda ctx: f"Implementing improvements: {ctx.get('research_gaps', '')[:60]}", "Implement"),
            WorkflowStep("validate", lambda ctx: f"Validating improvements: {ctx.get('implement_fixes', '')[:60]}", "Validate"),
        ])

        self._built_in_workflows = list(self.workflows.keys())

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def register_workflow(self, name: str, steps: List[WorkflowStep]) -> None:
        """Register a new named workflow."""
        self.workflows[name] = steps
        log.info(f"[AGENTIC] Workflow registered: '{name}' ({len(steps)} steps)")

    def run_workflow(self, name: str, initial_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a workflow by name.

        Returns a result dict with keys: workflow, steps, context, status.
        """
        if name not in self.workflows:
            return {"error": f"Workflow '{name}' not found", "available": list(self.workflows.keys())}

        log.info(f"[AGENTIC] ▶ Running workflow '{name}'")
        context: Dict[str, Any] = dict(initial_context or {})
        step_results: List[Dict[str, Any]] = []
        overall_status = "done"

        for step in self.workflows[name]:
            result = step.run(context)
            context[step.name] = result
            step_results.append({"step": step.name, "status": step.status, "result": result})
            if step.status == "failed":
                overall_status = "completed_with_failures"

        record = {
            "workflow": name,
            "steps": step_results,
            "context": context,
            "status": overall_status,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.history.append(record)

        if self.db:
            try:
                self.db.add_fact(f"agentic_workflow_{name}", str(step_results), tags=["agentic", name])
            except Exception:
                pass

        log.info(f"[AGENTIC] ✅ Workflow '{name}' completed — status: {overall_status}")
        return record

    def list_workflows(self) -> List[str]:
        """Return names of all registered workflows."""
        return list(self.workflows.keys())

    def workflow_status(self) -> Dict[str, Any]:
        """Return overview of registered workflows and recent history."""
        return {
            "registered_workflows": len(self.workflows),
            "workflows": list(self.workflows.keys()),
            "built_in": self._built_in_workflows,
            "executions_this_session": len(self.history),
            "last_run": self.history[-1]["workflow"] if self.history else None,
            "capability": "Multi-step autonomous task pipelines",
            "status": "Ready",
        }

    def format_result(self, record: Dict[str, Any]) -> str:
        """Format a workflow run result as human-readable text."""
        if "error" in record:
            return f"❌ Workflow error: {record['error']}\nAvailable: {', '.join(record.get('available', []))}"

        lines = [f"🤖 **AGENTIC WORKFLOW: {record['workflow'].upper()}**",
                 f"Status: {record['status']} | Steps: {len(record['steps'])}",
                 ""]
        for i, step in enumerate(record["steps"], 1):
            icon = "✅" if step["status"] == "done" else "❌"
            lines.append(f"{icon} Step {i} [{step['step']}]: {str(step['result'])[:120]}")

        return "\n".join(lines)
