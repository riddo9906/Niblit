import logging

from modules.structured_logging import configure_runtime_logging, log_exception


def test_configure_runtime_logging_writes_human_readable_and_json(tmp_path):
    log_file = tmp_path / "runtime.jsonl"
    logger = configure_runtime_logging(log_file=log_file, level=logging.INFO)

    logger.info("startup complete", event="startup", state="ready")

    assert logger.name == "NiblitRuntime"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "startup complete" in contents
    assert '"event": "startup"' in contents


def test_log_exception_emits_error_context(tmp_path):
    log_file = tmp_path / "exceptions.jsonl"
    logger = configure_runtime_logging(log_file=log_file, level=logging.ERROR)

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        log_exception(logger, "boot", exc, component="main", state="failed")

    contents = log_file.read_text(encoding="utf-8")
    assert "boom" in contents
    assert '"component": "main"' in contents
    assert '"state": "failed"' in contents
