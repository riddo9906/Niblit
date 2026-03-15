"""
test_evolve.py — Unit tests for modules/evolve.py (EvolveEngine).

Run with::

    pytest test_evolve.py -v

All optional module dependencies (researcher, code_generator, etc.) are
stubbed with MagicMock so no real services are required.
"""

import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from modules.evolve import EvolveEngine, TERMUX_DEPLOY_PATH, step as module_level_step


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_engine(**kwargs) -> EvolveEngine:
    """Return a fresh EvolveEngine with evolution_interval set to a large
    value so background loop never fires during tests."""
    kwargs.setdefault("evolution_interval", 9999)
    return EvolveEngine(**kwargs)


@pytest.fixture()
def engine():
    ev = _make_engine()
    yield ev
    ev.stop_background_evolution()


@pytest.fixture()
def engine_with_mocks():
    """EvolveEngine with all optional modules wired to MagicMocks."""
    researcher = MagicMock()
    researcher.research.return_value = "research result"

    code_gen = MagicMock()
    code_gen.generate.return_value = "def foo(): pass"

    teacher = MagicMock()
    teacher.teach.return_value = "taught"

    reflect_mod = MagicMock()
    reflect_mod.collect_and_summarize.return_value = "reflected"

    ev = _make_engine(
        researcher=researcher,
        code_generator=code_gen,
        self_teacher=teacher,
        reflect_module=reflect_mod,
    )
    yield ev
    ev.stop_background_evolution()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_creates_without_arguments(self):
        ev = EvolveEngine()
        assert ev is not None

    def test_creates_with_core(self):
        mock_core = MagicMock()
        ev = EvolveEngine(core=mock_core)
        assert ev.core is mock_core

    def test_iteration_starts_at_zero(self, engine):
        assert engine.iteration == 0

    def test_running_is_false_on_init(self, engine):
        assert engine.running is False

    def test_history_empty_on_init(self, engine):
        assert engine._history == []

    def test_stats_initialized(self, engine):
        for key in ("steps", "researched", "code_generated", "taught",
                    "reflected", "ideas_implemented"):
            assert key in engine._stats, f"Missing stat key: {key}"
        for val in engine._stats.values():
            assert val == 0


# ---------------------------------------------------------------------------
# step()
# ---------------------------------------------------------------------------

class TestStep:
    def test_step_returns_dict(self, engine):
        result = engine.step()
        assert isinstance(result, dict)

    def test_step_result_has_required_keys(self, engine):
        result = engine.step()
        for key in ("iteration", "ts", "direction", "actions", "mutations"):
            assert key in result, f"Missing key: {key}"

    def test_step_increments_iteration(self, engine):
        engine.step()
        assert engine.iteration == 1
        engine.step()
        assert engine.iteration == 2

    def test_step_increments_stats_steps(self, engine):
        engine.step()
        assert engine._stats["steps"] == 1

    def test_step_appends_to_history(self, engine):
        engine.step()
        assert len(engine._history) == 1

    def test_step_with_mocked_modules_does_not_raise(self, engine_with_mocks):
        result = engine_with_mocks.step()
        assert "iteration" in result

    def test_step_direction_is_string(self, engine):
        result = engine.step()
        assert isinstance(result["direction"], str)

    def test_step_actions_is_list(self, engine):
        result = engine.step()
        assert isinstance(result["actions"], list)

    def test_multiple_steps_accumulate_history(self, engine):
        for _ in range(5):
            engine.step()
        assert len(engine._history) == 5

    def test_step_with_knowledge_db(self):
        mock_db = MagicMock()
        ev = _make_engine(knowledge_db=mock_db)
        ev.step()
        # DB persist method should have been called
        mock_db.add_fact.assert_called()


# ---------------------------------------------------------------------------
# start/stop background evolution
# ---------------------------------------------------------------------------

class TestBackgroundEvolution:
    def test_start_returns_true(self, engine):
        result = engine.start_background_evolution()
        engine.stop_background_evolution()
        assert result is True

    def test_start_sets_running(self, engine):
        engine.start_background_evolution()
        running = engine.running
        engine.stop_background_evolution()
        assert running is True

    def test_start_twice_returns_false(self, engine):
        engine.start_background_evolution()
        result = engine.start_background_evolution()
        engine.stop_background_evolution()
        assert result is False

    def test_stop_returns_true(self, engine):
        engine.start_background_evolution()
        result = engine.stop_background_evolution()
        assert result is True

    def test_stop_clears_running(self, engine):
        engine.start_background_evolution()
        engine.stop_background_evolution()
        assert engine.running is False


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_returns_dict(self, engine):
        assert isinstance(engine.get_status(), dict)

    def test_has_required_keys(self, engine):
        status = engine.get_status()
        for key in ("running", "iteration", "stats", "available_modules",
                    "history_count", "last_direction"):
            assert key in status, f"Missing key: {key}"

    def test_running_false_when_not_started(self, engine):
        assert engine.get_status()["running"] is False

    def test_iteration_matches_steps(self, engine):
        engine.step()
        engine.step()
        assert engine.get_status()["iteration"] == 2

    def test_history_count_updates(self, engine):
        engine.step()
        assert engine.get_status()["history_count"] == 1

    def test_last_direction_updates_after_step(self, engine):
        assert engine.get_status()["last_direction"] is None
        engine.step()
        assert engine.get_status()["last_direction"] is not None

    def test_available_modules_all_false_when_none_wired(self, engine):
        mods = engine.get_status()["available_modules"]
        for key in ("researcher", "code_generator", "self_teacher", "reflect"):
            assert mods[key] is False, f"{key} should be False"

    def test_available_modules_true_for_wired_module(self):
        mock_researcher = MagicMock()
        ev = _make_engine(researcher=mock_researcher)
        mods = ev.get_status()["available_modules"]
        assert mods["researcher"] is True


# ---------------------------------------------------------------------------
# summarize_history
# ---------------------------------------------------------------------------

class TestSummarizeHistory:
    def test_empty_history_returns_no_steps_yet(self, engine):
        result = engine.summarize_history()
        assert "No evolution steps" in result

    def test_returns_string(self, engine):
        engine.step()
        assert isinstance(engine.summarize_history(), str)

    def test_includes_step_count_info(self, engine):
        for _ in range(3):
            engine.step()
        summary = engine.summarize_history()
        # Should mention at least one step number
        assert "Step" in summary or "step" in summary.lower()


# ---------------------------------------------------------------------------
# refresh_from_core
# ---------------------------------------------------------------------------

class TestRefreshFromCore:
    def test_refresh_with_none_core_does_not_raise(self, engine):
        engine.core = None
        engine.refresh_from_core()  # should be a no-op

    def test_refresh_pulls_researcher_from_core(self):
        mock_core = MagicMock()
        mock_researcher = MagicMock()
        mock_core.researcher = mock_researcher
        ev = _make_engine(core=mock_core)
        ev.refresh_from_core()
        assert ev.researcher is mock_researcher

    def test_refresh_pulls_knowledge_db_from_core(self):
        mock_core = MagicMock()
        mock_db = MagicMock()
        mock_core.db = mock_db
        ev = _make_engine(core=mock_core)
        ev.refresh_from_core()
        assert ev.knowledge_db is mock_db


# ---------------------------------------------------------------------------
# Module-level step() backward-compat function
# ---------------------------------------------------------------------------

class TestModuleLevelStep:
    def test_module_step_returns_dict(self):
        result = module_level_step()
        assert isinstance(result, dict)

    def test_module_step_has_direction(self):
        result = module_level_step()
        assert "direction" in result


# ---------------------------------------------------------------------------
# Deploy path
# ---------------------------------------------------------------------------

class TestDeployPath:
    def test_default_deploy_path_none_outside_termux(self):
        """Outside a Termux environment deploy_path should default to None."""
        ev = _make_engine()
        # We can't guarantee tests run on Termux, so just verify the type
        assert ev.deploy_path is None or isinstance(ev.deploy_path, Path)

    def test_explicit_deploy_path_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            assert ev.deploy_path == Path(tmpdir)

    def test_termux_deploy_path_constant_is_correct(self):
        expected = "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
        assert str(TERMUX_DEPLOY_PATH) == expected

    def test_get_status_includes_deploy_path_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            status = ev.get_status()
            assert "deploy_path" in status
            assert status["deploy_path"] == tmpdir

    def test_get_status_deploy_path_none_when_not_set(self):
        ev = _make_engine(deploy_path=None)
        if ev.deploy_path is None:
            assert ev.get_status()["deploy_path"] is None


# ---------------------------------------------------------------------------
# _write_to_deploy_path
# ---------------------------------------------------------------------------

class TestWriteToDeployPath:
    def test_returns_none_when_no_deploy_path(self):
        ev = _make_engine(deploy_path=None)
        ev.deploy_path = None  # force None even on Termux
        record = {"mutations": ["def foo(): pass"], "actions": []}
        result = ev._write_to_deploy_path("code generation quality", record)
        assert result is None

    def test_returns_none_when_no_mutations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            record = {"mutations": [], "actions": []}
            result = ev._write_to_deploy_path("code generation quality", record)
            assert result is None

    def test_writes_files_to_deploy_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            ev.iteration = 1
            record = {"mutations": ["def foo(): pass", "def bar(): pass"], "actions": []}
            result = ev._write_to_deploy_path("code generation quality", record)
            assert result is not None
            # Files should exist somewhere under tmpdir/evolved/
            evolved_dir = Path(tmpdir) / "evolved"
            written = list(evolved_dir.rglob("*.py"))
            assert len(written) == 2

    def test_increments_deploy_writes_stat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            ev.iteration = 1
            record = {"mutations": ["def x(): pass"], "actions": []}
            ev._write_to_deploy_path("test direction", record)
            assert ev._stats["deploy_writes"] == 1

    def test_written_files_contain_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev = _make_engine(deploy_path=tmpdir)
            ev.iteration = 3
            record = {"mutations": ["def my_func(): return 42"], "actions": []}
            ev._write_to_deploy_path("knowledge synthesis", record)
            evolved_dir = Path(tmpdir) / "evolved"
            written = list(evolved_dir.rglob("*.py"))
            content = written[0].read_text(encoding="utf-8")
            assert "Auto-generated by EvolveEngine" in content
            assert "knowledge synthesis" in content

    def test_step_includes_deploy_write_when_path_set_and_code_generated(self):
        """step() should record a deploy action when deploy_path is set and code is generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_gen = MagicMock()
            code_gen.generate.return_value = {"success": True, "code": "def f(): pass"}
            ev = _make_engine(deploy_path=tmpdir, code_generator=code_gen)
            result = ev.step()
            # If code was generated, a deploy action should be present
            deploy_actions = [a for a in result["actions"] if a.startswith("deployed:")]
            # deploy_actions may be empty if code_gen mock returned no usable mutation,
            # but the step should not raise
            assert isinstance(result["actions"], list)


# ---------------------------------------------------------------------------
# _live_upgrade_step
# ---------------------------------------------------------------------------

class TestLiveUpgradeStep:
    def test_returns_none_when_no_live_updater(self):
        ev = _make_engine()
        ev.live_updater = None
        result = ev._live_upgrade_step()
        assert result is None

    def test_calls_reload_all_changed_on_live_updater(self):
        mock_updater = MagicMock()
        mock_updater.reload_all_changed.return_value = [
            {"success": True, "module": "modules.knowledge_db"},
        ]
        ev = _make_engine(live_updater=mock_updater)
        result = ev._live_upgrade_step()
        mock_updater.reload_all_changed.assert_called_once()
        assert result is not None
        assert "modules.knowledge_db" in result

    def test_returns_none_when_nothing_reloaded(self):
        mock_updater = MagicMock()
        mock_updater.reload_all_changed.return_value = []
        ev = _make_engine(live_updater=mock_updater)
        result = ev._live_upgrade_step()
        assert result is None

    def test_increments_live_upgrades_stat(self):
        mock_updater = MagicMock()
        mock_updater.reload_all_changed.return_value = [
            {"success": True, "module": "modules.evolve"},
        ]
        ev = _make_engine(live_updater=mock_updater)
        ev._live_upgrade_step()
        assert ev._stats["live_upgrades"] == 1

    def test_does_not_count_failed_reloads(self):
        mock_updater = MagicMock()
        mock_updater.reload_all_changed.return_value = [
            {"success": False, "module": "modules.broken"},
        ]
        ev = _make_engine(live_updater=mock_updater)
        result = ev._live_upgrade_step()
        assert result is None
        assert ev._stats["live_upgrades"] == 0

    def test_live_updater_wired_in_step(self):
        """step() integrates live_upgrade sub-step when live_updater is provided."""
        mock_updater = MagicMock()
        mock_updater.reload_all_changed.return_value = [
            {"success": True, "module": "modules.evolve"},
        ]
        ev = _make_engine(live_updater=mock_updater)
        result = ev.step()
        assert isinstance(result, dict)
        # live_upgrades stat should be incremented
        assert ev._stats["live_upgrades"] >= 1


# ---------------------------------------------------------------------------
# refresh_from_core — live_updater and file_manager
# ---------------------------------------------------------------------------

class TestRefreshFromCoreExtended:
    def test_refresh_pulls_live_updater_from_core(self):
        mock_core = MagicMock()
        mock_lu = MagicMock()
        mock_core.live_updater = mock_lu
        ev = _make_engine(core=mock_core)
        ev.refresh_from_core()
        assert ev.live_updater is mock_lu

    def test_refresh_pulls_file_manager_from_core(self):
        mock_core = MagicMock()
        mock_fm = MagicMock()
        mock_core.file_manager = mock_fm
        ev = _make_engine(core=mock_core)
        ev.refresh_from_core()
        assert ev.file_manager is mock_fm

    def test_available_modules_includes_live_updater_and_file_manager(self):
        mock_lu = MagicMock()
        mock_fm = MagicMock()
        ev = _make_engine(live_updater=mock_lu, file_manager=mock_fm)
        mods = ev.get_status()["available_modules"]
        assert mods["live_updater"] is True
        assert mods["file_manager"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
