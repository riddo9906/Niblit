import io
import time

from modules.boot_diagnostics import BootDiagnostics
from modules.boot_diagnostics import ProcessDiagnostics


def test_boot_diagnostics_records_success_and_summary() -> None:
    messages: list[str] = []
    boot = BootDiagnostics(emitter=messages.append)

    stage = boot.start("Starting Niblit Core")
    boot.success(stage, "core ready")
    boot.summary()

    assert any("[BOOT 01] Starting Niblit Core — start" in msg for msg in messages)
    assert any("[BOOT 01] Starting Niblit Core — success" in msg for msg in messages)
    assert any("Niblit Runtime Fully Operational" in msg for msg in messages)


def test_boot_diagnostics_records_last_successful_phase_on_failure() -> None:
    messages: list[str] = []
    boot = BootDiagnostics(emitter=messages.append)

    ok_stage = boot.start("Loading configuration")
    boot.success(ok_stage)
    fail_stage = boot.start("UI startup")
    try:
        raise TimeoutError("ui timed out")
    except TimeoutError as exc:
        boot.failure(fail_stage, exc, include_traceback=False)

    assert any("last successful phase: Loading configuration" in msg for msg in messages)


def test_process_diagnostics_logs_start_and_failure_output() -> None:
    messages: list[str] = []
    proc = ProcessDiagnostics(
        name="UI",
        command=["npm", "run", "dev"],
        cwd=None,
        pid=123,
        stdout=io.StringIO("line1\nline2\n"),
        stderr=io.StringIO("err1\n"),
        emitter=messages.append,
    )

    time.sleep(0.05)
    proc.log_started()
    proc.dump_failure(exit_code=1)

    assert any("pid=123" in msg for msg in messages)
    assert any("stdout tail" in msg and "line1" in msg for msg in messages)
    assert any("stderr tail" in msg and "err1" in msg for msg in messages)
