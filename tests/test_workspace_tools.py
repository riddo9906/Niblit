"""Tests for modules/workspace_tools.py — Phase 5D governed LLM workspace.

Covers: policy rejection (traversal/absolute/secrets/extension), bounded
list/search/read against the REAL repository (same authority as the UI file
tab), governed write/edit with backups + EventBus events, and the bounded
test runner. Write/test operations run in an isolated temp workspace via
NIBLIT_WORKSPACE_ROOT so the real repository is never mutated.
"""

import pytest
from pathlib import Path

from modules import workspace_tools as wt


def _use_repository_workspace(monkeypatch):
    """Opt these read-only fixtures into the source tree under test."""
    repository = Path(wt.__file__).resolve().parent.parent
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(repository))


# ---------------------------------------------------------------------------
# Policy rejection (read surface)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_path", [
    "../niblit-ui/package.json",
    "modules/../server.py",
    r"safe\..\private.py",
    "..",
    "C:/Windows/win.ini",
    r"C:\Windows\win.ini",
    r"\\server\share\private.txt",
    "/etc/passwd",
])
def test_read_rejects_traversal_and_absolute_paths(bad_path):
    result = wt.read_workspace(bad_path)
    assert "error" in result
    assert result.get("content") is None


@pytest.mark.parametrize("bad_path", [
    ".env",
    ".env.local",
    ".git/config",
    ".git/HEAD",
    "secrets/keys.json",
    "modules/api_keys.py",
    "deploy/id_rsa",
    "certs/server.pem",
    "modules/tokenizer_trainer.py",   # real file: 'token' deny-list
])
def test_read_rejects_secret_locations(bad_path):
    result = wt.read_workspace(bad_path)
    assert "error" in result
    assert "protected/secret" in result["error"]


def test_read_rejects_disallowed_file_types(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    binary = tmp_path / "payload.exe"
    binary.write_bytes(b"MZ...")
    result = wt.read_workspace("payload.exe")
    assert "not permitted" in result["error"]


def test_read_missing_file_is_structured_not_raised():
    result = wt.read_workspace("modules/definitely_not_here.py")
    assert result == {"error": "not_found",
                      "path": "modules/definitely_not_here.py"}


# ---------------------------------------------------------------------------
# Read surface against the REAL repository (same authority as the UI)
# ---------------------------------------------------------------------------

def test_read_real_python_source_through_renderer_authority(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.read_workspace("modules/trading_read_tools.py", max_chars=800)
    assert "error" not in result
    # REAL source, not a summary: the actual module docstring must appear.
    assert result["content"].startswith('"""')
    assert "trading" in result["content"].lower()
    assert result["language"] == "python"
    assert result["truncated"] is True
    assert result["returned_chars"] == 800


def test_read_real_markdown_file(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.read_workspace("AGENTS.md", max_chars=400)
    if "error" in result:  # file optional in repo
        pytest.skip("AGENTS.md not present")
    assert result["size"] > 0
    assert result["returned_chars"] <= 400


def test_read_respects_max_chars_budget(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.read_workspace("modules/event_bus.py", max_chars=500)
    assert "error" not in result
    assert len(result["content"]) <= 500
    assert result["truncated"] is True


def test_list_real_modules_dir_is_bounded_and_typed(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.list_workspace("modules", max_entries=25)
    assert "error" not in result
    assert result["count"] <= 25
    assert result["truncated"] is True  # modules/ holds far more than 25
    for entry in result["entries"][:5]:
        assert entry["path"].startswith("modules")
        assert entry["type"] in ("file", "dir")
        if entry["type"] == "file":
            assert isinstance(entry["size"], int)
            assert "modified_at" in entry


def test_list_hides_secret_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "visible.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "app_secrets.json").write_text("{}", encoding="utf-8")
    result = wt.list_workspace("")
    names = {e["name"] for e in result["entries"]}
    assert "visible.py" in names
    assert ".env" not in names
    assert "app_secrets.json" not in names


class RecordingBus:
    """Minimal EventBus test double that records published events."""

    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


# ---------------------------------------------------------------------------
# Search surface
# ---------------------------------------------------------------------------

def test_search_finds_real_content_with_line_numbers(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.search_workspace("class GovernedSearch", "modules",
                                 max_results=10)
    assert "error" not in result
    assert result["content_matches"], "expected a real source hit"
    hit = result["content_matches"][0]
    assert hit["path"] == "modules/governed_research.py"
    assert hit["line_number"] > 0
    assert "class GovernedSearch" in hit["line_text"]


def test_search_matches_file_names_too(monkeypatch):
    _use_repository_workspace(monkeypatch)
    result = wt.search_workspace("research_orchestrator", "modules",
                                 max_results=10)
    assert "modules/research_orchestrator.py" in result["name_matches"]


def test_search_rejects_empty_query():
    assert wt.search_workspace("   ") == {"error": "empty_query"}


def test_search_scoped_to_subdirectory(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "alpha.py").write_text("NEEDLE_HERE\n",
                                               encoding="utf-8")
    (tmp_path / "beta.py").write_text("NEEDLE_HERE\n", encoding="utf-8")
    result = wt.search_workspace("NEEDLE_HERE", "pkg")
    paths = {m["path"] for m in result["content_matches"]}
    assert paths == {"pkg/alpha.py"}


def test_search_result_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    for i in range(8):
        (tmp_path / f"file_{i}.txt").write_text("hit\n" * 30,
                                                encoding="utf-8")
    result = wt.search_workspace("hit", "", max_results=5)
    assert len(result["content_matches"]) <= 5
    assert result["truncated"] is True


def test_python_inspection_returns_structure_without_executing(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    marker = tmp_path / "executed.txt"
    (tmp_path / "sample.py").write_text(
        '"""Small sample module."""\n'
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "class Worker:\n"
        "    def run(self, value):\n"
        "        return value\n"
        "async def helper():\n"
        "    return None\n",
        encoding="utf-8",
    )

    result = wt.inspect_python_workspace("sample.py")

    assert "error" not in result
    assert result["module_docstring"] == "Small sample module."
    assert any(row["module"] == "pathlib" for row in result["imports"])
    assert any(row["kind"] == "class" and row["name"] == "Worker"
               and row["line_start"] == 4 for row in result["definitions"])
    assert any(row["kind"] == "method" and row["name"] == "run"
               and row["class"] == "Worker" and row["line_start"] == 5
               for row in result["definitions"])
    assert not marker.exists(), "AST inspection must never execute source"


def test_python_inspection_reports_syntax_and_type_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("text\n", encoding="utf-8")

    syntax = wt.inspect_python_workspace("broken.py")
    wrong_type = wt.inspect_python_workspace("notes.md")

    assert syntax["error"] == "syntax_error"
    assert syntax["line"] == 1
    assert wrong_type["error"] == "python_source_required"


def test_workspace_read_rejects_symlink_to_protected_or_outside_file(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private = True\n", encoding="utf-8")
    protected = root / ".env"
    protected.write_text("PRIVATE=1\n", encoding="utf-8")
    try:
        (root / "outside_alias.py").symlink_to(outside)
        (root / "settings.py").symlink_to(protected)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    outside_result = wt.read_workspace("outside_alias.py")
    protected_result = wt.read_workspace("settings.py")

    assert "error" in outside_result
    assert "error" in protected_result


# ---------------------------------------------------------------------------
# Governed write / edit (isolated temp workspace)
# ---------------------------------------------------------------------------

def test_write_creates_file_and_emits_events(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    bus = RecordingBus()
    result = wt.write_workspace("generated/hello.py",
                                "VALUE = 41\n", event_bus=bus)
    assert "error" not in result, result
    assert result["written"] is True
    assert (tmp_path / "generated" / "hello.py").read_text(
        encoding="utf-8") == "VALUE = 41\n"
    types = [e.type for e in bus.events]
    assert types == ["code.change.started", "code.change.completed"]


def test_write_keeps_backup_on_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "note.txt"
    target.write_text("original\n", encoding="utf-8")
    result = wt.write_workspace("note.txt", "replaced\n")
    assert "error" not in result
    assert target.read_text(encoding="utf-8") == "replaced\n"
    assert result["backup_path"], "backup of the original must exist"


def test_write_rejects_secrets_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    assert "protected/secret" in wt.write_workspace(
        ".env", "X=1")["error"]
    assert "protected/secret" in wt.write_workspace(
        "creds/api_key.txt", "X=1")["error"]
    assert "traversal" in wt.write_workspace(
        "../outside.txt", "X=1")["error"]
    assert not (tmp_path / ".env").exists()


def test_write_rejects_oversized_content(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    big = "x" * (wt.MAX_WRITE_BYTES + 1)
    result = wt.write_workspace("big.txt", big)
    assert "content too large" in result["error"]


def test_edit_replaces_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a - b  # BUG\n",
                      encoding="utf-8")
    result = wt.edit_workspace(
        "calc.py", "return a - b  # BUG", "return a + b")
    assert "error" not in result, result
    text = target.read_text(encoding="utf-8")
    assert "return a + b" in text
    assert "BUG" not in text
    assert result["backup_path"], "edit must keep a backup"


def test_edit_rejects_ambiguous_and_missing_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "twice.txt"
    target.write_text("dup\nmid\ndup\n", encoding="utf-8")
    multi = wt.edit_workspace("twice.txt", "dup", "new")
    assert "exactly once" in multi["error"]
    assert target.read_text(encoding="utf-8") == "dup\nmid\ndup\n"
    missing = wt.edit_workspace("twice.txt", "nope", "new")
    assert "not found" in missing["error"]


def test_edit_preserves_crlf_line_endings(tmp_path, monkeypatch):
    """Regression: a CRLF file edited through the governed path must keep
    its exact byte-level line endings (write_text newline translation used
    to produce \\r\\r\\n corruption, and the delegate silently no-opped when
    the LF-form old_text did not match the raw CRLF content)."""
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "win.py"
    target.write_bytes(b"def f():\r\n    return 1  # FIX\r\n")
    result = wt.edit_workspace("win.py", "return 1  # FIX", "return 2")
    assert "error" not in result, result
    raw = target.read_bytes()
    assert b"return 2" in raw
    assert raw.count(b"\r\n") == 2, "CRLF endings must be preserved exactly"
    assert raw.count(b"\r\r") == 0, "no double-CR corruption allowed"


def test_filesystem_manager_patch_fails_on_missing_match(tmp_path):
    """Regression: FilesystemManager.patch_file used to report success on a
    zero-match replace (fabricated edit). It must fail explicitly."""
    from modules.filesystem_manager import FilesystemManager

    target = tmp_path / "doc.txt"
    target.write_text("hello world\n", encoding="utf-8")
    fm = FilesystemManager(base_dir=str(tmp_path))
    result = fm.patch_file(str(target), "not-there", "x")
    assert result["success"] is False
    assert "not found" in result["error"]
    assert target.read_text(encoding="utf-8") == "hello world\n"


# ---------------------------------------------------------------------------
# Bounded test runner
# ---------------------------------------------------------------------------

def test_run_tests_executes_real_passing_test(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_smoke_tmp.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    result = wt.run_tests("tests/test_smoke_tmp.py", timeout=120)
    assert result.get("passed") is True, result
    assert result["returncode"] == 0
    assert "1 passed" in result["output_tail"]


def test_run_tests_reports_real_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bad_tmp.py").write_text(
        "def test_bad():\n    assert 1 + 1 == 3\n", encoding="utf-8")
    result = wt.run_tests("tests/test_bad_tmp.py", timeout=120)
    assert result.get("passed") is False
    assert result["returncode"] != 0


def test_run_tests_rejects_non_test_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "server.py").write_text("print('hi')\n", encoding="utf-8")
    result = wt.run_tests("server.py")
    assert "only test paths" in result["error"]


def test_run_tests_rejects_out_of_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    result = wt.run_tests("../Niblit/tests/test_workspace_tools.py")
    assert "error" in result


# ---------------------------------------------------------------------------
# Governed loop wiring
# ---------------------------------------------------------------------------

def test_governed_loop_registers_all_workspace_capabilities():
    from modules.core_tool_runtime import (build_governed_tool_loop,
                                           WORKSPACE_FUNCTION_SCHEMAS)

    loop = build_governed_tool_loop(lambda: None)
    for name in ("workspace_list", "workspace_search", "workspace_read",
                 "workspace_read_pdf", "workspace_inspect_python",
                 "workspace_write", "workspace_edit", "run_tests"):
        assert name in loop.allowed_tool_names()
        assert name in WORKSPACE_FUNCTION_SCHEMAS


def test_workspace_results_flow_through_loop_validator(monkeypatch):
    """Tool dispatch must work through the REAL LlmToolLoop tool map."""
    _use_repository_workspace(monkeypatch)
    from modules.core_tool_runtime import build_governed_tool_loop

    loop = build_governed_tool_loop(lambda: None)
    listed = loop._tool_map["workspace_list"](path="modules", max_entries=3)
    assert listed["count"] <= 3
    read = loop._tool_map["workspace_read"](path="modules/event_bus.py",
                                            max_chars=300)
    assert read["content"], "real content required"


def test_workspace_pdf_read_extracts_page_text_and_enforces_workspace_boundary(
    tmp_path, monkeypatch
):
    import sys
    import types
    from modules import workspace_tools as wt

    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "brief.pdf").write_bytes(b"%PDF-test")
    pages = [types.SimpleNamespace(
        extract_text=lambda: "Quarterly report: revenue grew.")]
    fake_reader = types.SimpleNamespace(is_encrypted=False, pages=pages)
    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(
        PdfReader=lambda _path, strict=False: fake_reader))

    result = wt.read_workspace_pdf("brief.pdf")
    assert result["text"] == "[Page 1]\nQuarterly report: revenue grew."
    assert result["page_count"] == 1
    assert result["pages"][0]["page"] == 1
    assert not result["needs_ocr"]

    denied = wt.read_workspace_pdf("../outside.pdf")
    assert "error" in denied
    (tmp_path / "not-a-pdf.txt").write_text("private", encoding="utf-8")
    assert wt.read_workspace_pdf("not-a-pdf.txt")["error"] == "pdf_file_required"


def test_workspace_pdf_read_reports_image_only_document(tmp_path, monkeypatch):
    import sys
    import types
    from modules import workspace_tools as wt

    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-test")
    fake_reader = types.SimpleNamespace(
        is_encrypted=False,
        pages=[types.SimpleNamespace(extract_text=lambda: "")],
    )
    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(
        PdfReader=lambda _path, strict=False: fake_reader))

    result = wt.read_workspace_pdf("scan.pdf")
    assert result["error"] == "no_extractable_text"
    assert result["needs_ocr"] is True
