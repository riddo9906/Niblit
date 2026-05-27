#!/usr/bin/env python3
"""NiblitDevAgent — governed cognitive development runtime (Phase 2)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from agents.niblit_dev_agent.approval_manager import ApprovalManager
from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.context_engine import ContextEngine
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.filesystem_guard import FilesystemGuard
from agents.niblit_dev_agent.governed_executor import GovernedExecutor
from agents.niblit_dev_agent.memory_bridge import MemoryBridge
from agents.niblit_dev_agent.planning_engine import PlanningEngine
from agents.niblit_dev_agent.provider_awareness import ProviderAwareness
from agents.niblit_dev_agent.rollback_manager import RollbackManager
from agents.niblit_dev_agent.runtime_awareness import RuntimeAwareness
from agents.niblit_dev_agent.task_contracts import (
    CLI_ANALYZE,
    CLI_APPROVE,
    CLI_ARCHITECTURE,
    CLI_EXECUTE,
    CLI_PROVIDERS,
    CLI_ROLLBACK,
    CLI_RUNTIME,
    CLI_STATUS,
    DEV_AGENT_ANALYZE_TASK_TYPE,
    DEV_AGENT_EXECUTE_TASK_TYPE,
    DEV_AGENT_TASK_TYPE,
    DevTaskContract,
)
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.task_queue import Task

log = logging.getLogger("NiblitDevAgent")


class NiblitDevAgent(BaseAgent):
    """Internal cognitive-engineering runtime agent for Niblit."""

    HANDLED_TASK_TYPES = [
        DEV_AGENT_TASK_TYPE,
        DEV_AGENT_ANALYZE_TASK_TYPE,
        DEV_AGENT_EXECUTE_TASK_TYPE,
    ]

    def __init__(
        self,
        *,
        core: Any | None = None,
        runtime_manager: Any | None = None,
        event_bus: Any | None = None,
        telemetry: Any | None = None,
        local_brain: Any | None = None,
        router_v2: Any | None = None,
        llm_provider_manager: Any | None = None,
        repo_root: str | None = None,
    ) -> None:
        super().__init__("niblit_dev_agent")
        self._core = core
        self._runtime_manager = runtime_manager
        self._event_bus = event_bus or getattr(runtime_manager, "event_bus", None)
        self._telemetry_hooks = DevAgentTelemetryHooks(telemetry=telemetry)

        root = repo_root or str(Path(__file__).resolve().parents[2])
        self._architecture_indexer = ArchitectureIndexer(root)
        self._provider_awareness = ProviderAwareness(
            local_brain=local_brain,
            router_v2=router_v2,
            llm_provider_manager=llm_provider_manager,
        )
        self._memory_bridge = MemoryBridge(authority="niblit_dev_agent")
        self._runtime_awareness = RuntimeAwareness(
            core=core,
            runtime_manager=runtime_manager,
            event_bus=self._event_bus,
            telemetry=telemetry,
            local_brain=local_brain,
        )
        self._context_engine = ContextEngine(
            runtime_awareness=self._runtime_awareness,
            provider_awareness=self._provider_awareness,
            architecture_indexer=self._architecture_indexer,
            memory_bridge=self._memory_bridge,
            telemetry=self._telemetry_hooks,
        )
        self._event_subscriber = EventSubscriber(self._event_bus, self._telemetry_hooks)
        self._event_subscriber.subscribe()

        # Phase-2 components ──────────────────────────────────────────────────
        self._planning_engine = PlanningEngine(
            architecture_indexer=self._architecture_indexer,
            telemetry=self._telemetry_hooks,
        )
        self._filesystem_guard = FilesystemGuard(
            repo_root=root,
            telemetry=self._telemetry_hooks,
        )
        self._rollback_manager = RollbackManager(
            repo_root=root,
            telemetry=self._telemetry_hooks,
        )
        self._approval_manager = ApprovalManager(telemetry=self._telemetry_hooks)
        self._governed_executor = GovernedExecutor(
            approval_manager=self._approval_manager,
            filesystem_guard=self._filesystem_guard,
            rollback_manager=self._rollback_manager,
            telemetry=self._telemetry_hooks,
            event_bus=self._event_bus,
        )

        self._startup_snapshot = self._runtime_awareness.get_runtime_snapshot()
        self._telemetry_hooks.increment("dev_agent_startups_total", 1)
        self._telemetry_hooks.gauge(
            "dev_agent_startup_threads",
            float(self._startup_snapshot.get("active_threads", {}).get("count", 0)),
        )

    # ── Phase-1 snapshot accessors ────────────────────────────────────────────

    def get_runtime_snapshot(self) -> dict[str, Any]:
        with self._telemetry_hooks.timed("dev_agent_runtime_snapshot_ms"):
            return self._runtime_awareness.get_runtime_snapshot()

    def get_provider_snapshot(self) -> dict[str, Any]:
        with self._telemetry_hooks.timed("dev_agent_provider_snapshot_ms"):
            return self._provider_awareness.get_provider_snapshot()

    def get_architecture_summary(self) -> dict[str, Any]:
        with self._telemetry_hooks.timed("dev_agent_architecture_snapshot_ms"):
            return self._architecture_indexer.index()

    def get_status(self) -> dict[str, Any]:
        return {
            **super().get_status(),
            "task_types": list(self.HANDLED_TASK_TYPES),
            "event_metrics": self._event_subscriber.metrics(),
            "telemetry": {
                "available": bool(self._telemetry_hooks.snapshot()),
            },
            "deployment_mode": self.get_runtime_snapshot().get("deployment_mode", "unknown"),
        }

    # ── Phase-2 analysis / planning accessors ─────────────────────────────────

    def analyze_scope(self, scope: str) -> dict[str, Any]:
        """Run architecture-aware scope analysis."""
        provider = self.get_provider_snapshot()
        runtime = self.get_runtime_snapshot()
        self._planning_engine.update_snapshots(
            provider_snapshot=provider,
            runtime_snapshot=runtime,
        )
        return self._planning_engine.analyze_scope(scope)

    def plan_task(
        self,
        scope: str,
        description: str = "",
        affected_modules: list[str] | None = None,
        task_type: str = "analysis",
    ) -> dict[str, Any]:
        """Plan a governed development task; return contract as dict."""
        provider = self.get_provider_snapshot()
        runtime = self.get_runtime_snapshot()
        self._planning_engine.update_snapshots(
            provider_snapshot=provider,
            runtime_snapshot=runtime,
        )
        contract = self._planning_engine.plan_task(
            scope=scope,
            description=description,
            affected_modules=affected_modules,
            task_type=task_type,
        )
        return contract.to_dict()

    def stage_task(
        self,
        *,
        scope: str,
        description: str,
        affected_modules: list[str],
        staged_mutations: list[dict[str, Any]],
        restart_required: bool = False,
    ) -> dict[str, Any]:
        """Create a staged plan that requires explicit approval before execution."""
        contract = DevTaskContract.from_dict(
            self.plan_task(
                scope=scope,
                description=description,
                affected_modules=affected_modules,
            )
        )
        plan_id = contract.task_id
        for mutation in staged_mutations:
            op = str(mutation.get("operation", "write"))
            relpath = str(mutation.get("relpath", ""))
            if op == "delete":
                self._filesystem_guard.stage_delete(plan_id, relpath)
            else:
                self._filesystem_guard.stage_write(
                    plan_id,
                    relpath,
                    str(mutation.get("content", "")),
                )

        manifest = self._filesystem_guard.mutation_manifest(
            plan_id=plan_id,
            contract=contract,
            affected_runtime_systems=list(affected_modules),
            restart_required=restart_required,
        )
        staged_plan = self._filesystem_guard.staged_plan(plan_id)
        staged_record = self._approval_manager.stage_task(
            contract,
            staged_plan={"plan_id": plan_id, **staged_plan},
            mutation_manifest=manifest,
            metadata={"description": description},
        )
        self._telemetry_hooks.increment("dev_agent_tasks_staged_total", 1)
        return staged_record

    # ── CLI handler ───────────────────────────────────────────────────────────

    def handle_cli(self, text: str) -> str:
        # Split into action + optional argument
        parts = (text or "").strip().split(maxsplit=1)
        action = parts[0].lower() if parts else CLI_STATUS
        arg = parts[1] if len(parts) > 1 else ""

        result = self._dispatch_cli(action, arg)
        self._emit_command_event(action, result)
        return result

    def _dispatch_cli(self, action: str, arg: str) -> str:
        """Dispatch a parsed CLI action and return the response string."""
        if action == CLI_STATUS:
            with self._telemetry_hooks.timed("dev_agent_cli_status_ms"):
                st = self.get_status()
            ev = st.get("event_metrics", {})
            return (
                "NiblitDevAgent\n"
                f"  state: {st.get('state')}\n"
                f"  task_types: {', '.join(st.get('task_types', []))}\n"
                f"  events_seen: {ev.get('events_total', 0)}\n"
                f"  workflow_suggestions: {ev.get('workflow_suggestions_total', 0)}\n"
                f"  approvals_pending: {len(self._approval_manager.list_pending())}\n"
                f"  deployment_mode: {st.get('deployment_mode', 'unknown')}"
            )

        if action == CLI_RUNTIME:
            with self._telemetry_hooks.timed("dev_agent_cli_runtime_ms"):
                rt = self.get_runtime_snapshot()
            topo = rt.get("runtime_topology", {})
            threads = rt.get("active_threads", {})
            return (
                "NiblitDevAgent Runtime\n"
                f"  deployment_mode: {rt.get('deployment_mode', 'unknown')}\n"
                f"  runtime_manager: {topo.get('runtime_manager_available', False)}\n"
                f"  event_bus: {topo.get('event_bus_available', False)}\n"
                f"  telemetry: {topo.get('telemetry_available', False)}\n"
                f"  local_brain: {topo.get('local_brain_available', False)}\n"
                f"  threads: {threads.get('count', 0)}"
            )

        if action == CLI_PROVIDERS:
            with self._telemetry_hooks.timed("dev_agent_cli_providers_ms"):
                providers = self.get_provider_snapshot()
            return (
                "NiblitDevAgent Providers\n"
                f"  active: {providers.get('active_provider', 'unknown')}\n"
                f"  fallback_available: {providers.get('fallback_available', False)}\n"
                f"  health: {providers.get('provider_health', {})}\n"
                f"  last_route: {providers.get('router_last_route', {})}"
            )

        if action == CLI_ARCHITECTURE:
            with self._telemetry_hooks.timed("dev_agent_cli_architecture_ms"):
                arch = self.get_architecture_summary()
            return (
                "NiblitDevAgent Architecture\n"
                f"  runtime_modules: {len(arch.get('runtime_modules', []))}\n"
                f"  deployment_boundaries: {len(arch.get('deployment_boundaries', []))}\n"
                f"  event_runtime_systems: {len(arch.get('event_runtime_systems', []))}\n"
                f"  scan_duration_ms: {arch.get('scan_duration_ms', 0)}"
            )

        if action == CLI_ANALYZE:
            scope = arg.strip() or "niblit_core"
            with self._telemetry_hooks.timed("dev_agent_cli_analyze_ms"):
                analysis = self.analyze_scope(scope)
            touched = analysis.get("touched_modules", [])
            provider_ctx = analysis.get("provider_context", {})
            runtime_ctx = analysis.get("runtime_context", {})
            return (
                f"NiblitDevAgent Analysis: '{scope}'\n"
                f"  analysis_duration_ms: {analysis.get('analysis_duration_ms', 0)}\n"
                f"  touched_modules: {len(touched)}\n"
                f"  touched: {touched[:5]}{'...' if len(touched) > 5 else ''}\n"
                f"  runtime_mode: {runtime_ctx.get('runtime_mode', 'unknown')}\n"
                f"  deployment_mode: {runtime_ctx.get('deployment_mode', 'unknown')}\n"
                f"  provider: {provider_ctx.get('active_provider', 'unknown')}"
            )

        if action == CLI_APPROVE:
            return self._cli_approve(arg)

        if action == CLI_EXECUTE:
            return self._cli_execute(arg)

        if action == CLI_ROLLBACK:
            return self._cli_rollback(arg)

        return (
            "Usage: dev-agent <status|runtime|providers|architecture|analyze [scope]"
            "|approve ...|execute <task_id>|rollback <task_id>>\n"
            "Examples: dev-agent status, dev-agent analyze modules/local_brain.py, "
            "dev-agent approve <task_id> --ack-risk --confirm-rollback, "
            "dev-agent execute <task_id>, dev-agent rollback <task_id>"
        )

    def _emit_command_event(self, action: str, result: str) -> None:
        """Publish a command.executed event to the EventBus for observability."""
        if self._event_bus is None:
            return
        try:
            from modules.event_bus import EVENT_COMMAND_EXECUTED, NiblitEvent
            self._event_bus.publish(NiblitEvent(
                type=EVENT_COMMAND_EXECUTED,
                source="niblit_dev_agent",
                payload={
                    "command": f"dev-agent {action}",
                    "result_length": len(result),
                    "success": "Error" not in result and "failed" not in result.lower(),
                },
            ))
        except Exception:
            pass

    def _cli_approve(self, arg: str) -> str:
        """Handle the 'approve' sub-command."""
        tokens = arg.split()
        if not tokens:
            pending = self._approval_manager.list_pending()
            if not pending:
                return "NiblitDevAgent Approvals\n  pending: 0"
            task_ids = [str(r.get("task_id", "")) for r in pending][:10]
            return (
                "NiblitDevAgent Approvals\n"
                f"  pending: {len(pending)}\n"
                f"  task_ids: {task_ids}"
            )

        task_id = tokens[0]
        runtime_risk_ack = "--ack-risk" in tokens
        rollback_confirm = "--confirm-rollback" in tokens
        allow_protected = "--allow-protected" in tokens
        if not runtime_risk_ack or not rollback_confirm:
            return (
                "Approval rejected: explicit acknowledgements required.\n"
                "Usage: dev-agent approve <task_id> --ack-risk --confirm-rollback [--allow-protected]"
            )
        try:
            approved = self._approval_manager.approve_task(
                task_id,
                approver="dev-agent-cli",
                runtime_risk_acknowledged=runtime_risk_ack,
                rollback_confirmed=rollback_confirm,
                metadata={"allow_protected_writes": allow_protected},
            )
            if self._runtime_manager is not None:
                self._runtime_manager.submit_task(
                    DEV_AGENT_EXECUTE_TASK_TYPE,
                    payload={"task_id": task_id},
                    priority="high",
                    source="dev_agent_approval",
                )
                self._runtime_manager.dispatch_pending(max_tasks=1)
            self._telemetry_hooks.increment("dev_agent_approvals_total", 1)
            return (
                "NiblitDevAgent Approval\n"
                f"  task_id: {task_id}\n"
                f"  approved: {approved.get('runtime_risk_acknowledged', False)}\n"
                "  execution: queued via RuntimeManager"
            )
        except Exception as exc:
            return f"NiblitDevAgent Approval Error: {exc}"

    def _cli_execute(self, arg: str) -> str:
        """Handle 'dev-agent execute <task_id>' — run an approved task immediately."""
        task_id = arg.strip()
        if not task_id:
            pending = self._approval_manager.list_pending()
            approved_ids = [
                str(r.get("task_id", ""))
                for r in pending
                if r.get("state") == "approved"
            ]
            if not approved_ids:
                return "NiblitDevAgent Execute\n  no approved tasks pending"
            return (
                "NiblitDevAgent Execute\n"
                f"  approved_tasks: {approved_ids[:10]}\n"
                "Usage: dev-agent execute <task_id>"
            )
        try:
            with self._telemetry_hooks.timed("dev_agent_cli_execute_ms"):
                exec_result = self._governed_executor.execute_approved_task(task_id)
            self._telemetry_hooks.increment("dev_agent_executions_total", 1)
            status = exec_result.get("status", "unknown")
            return (
                "NiblitDevAgent Execute\n"
                f"  task_id: {task_id}\n"
                f"  status: {status}\n"
                f"  mutations_applied: {exec_result.get('mutations_applied', 0)}"
            )
        except Exception as exc:
            return f"NiblitDevAgent Execute Error: {exc}"

    def _cli_rollback(self, arg: str) -> str:
        """Handle 'dev-agent rollback <task_id>' — rollback an executed task."""
        task_id = arg.strip()
        if not task_id:
            return (
                "NiblitDevAgent Rollback\n"
                "Usage: dev-agent rollback <task_id>"
            )
        try:
            with self._telemetry_hooks.timed("dev_agent_cli_rollback_ms"):
                rb_result = self._rollback_manager.rollback(task_id)
            self._telemetry_hooks.increment("dev_agent_rollbacks_total", 1)
            status = rb_result.get("status", "unknown") if isinstance(rb_result, dict) else str(rb_result)
            return (
                "NiblitDevAgent Rollback\n"
                f"  task_id: {task_id}\n"
                f"  status: {status}"
            )
        except Exception as exc:
            return f"NiblitDevAgent Rollback Error: {exc}"

    def _execute(self, task: Task, event_bus: Any) -> dict[str, Any]:
        _ = event_bus
        query = str(task.payload.get("query", CLI_STATUS)).strip().lower()
        if task.task_type == DEV_AGENT_EXECUTE_TASK_TYPE or query == DEV_AGENT_EXECUTE_TASK_TYPE:
            task_id = str(task.payload.get("task_id", ""))
            if not task_id:
                return {"error": "missing_task_id"}
            return {
                "query": DEV_AGENT_EXECUTE_TASK_TYPE,
                "task_id": task_id,
                "result": self._governed_executor.execute_approved_task(task_id),
            }
        if query == DEV_AGENT_ANALYZE_TASK_TYPE or task.task_type == DEV_AGENT_ANALYZE_TASK_TYPE:
            scope = str(task.payload.get("scope", "niblit_core"))
            return {
                "query": CLI_ANALYZE,
                "scope": scope,
                "result": self.analyze_scope(scope),
            }
        if query in {CLI_STATUS, CLI_RUNTIME, CLI_PROVIDERS, CLI_ARCHITECTURE, CLI_ANALYZE, CLI_APPROVE}:
            return {
                "query": query,
                "result": self.handle_cli(query),
                "context": self._context_engine.build_context() if query == CLI_STATUS else {},
            }
        return self._context_engine.build_context()


def get_default_repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
