from modules.boot_diagnostics import BootDiagnostics


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
