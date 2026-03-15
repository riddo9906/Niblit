"""
test_code_tools.py — Unit tests for CodeCompiler.syntax_test and
CodeGenerator.validate_structure / ensure_structure / generate_with_validation,
plus new language templates, BinaryTools, and ALE expanded topics.

Run with::

    pytest test_code_tools.py -v
"""

from unittest.mock import MagicMock
import pytest
from modules.code_compiler import CodeCompiler
from modules.code_generator import CodeGenerator


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def compiler():
    return CodeCompiler()


@pytest.fixture()
def generator():
    return CodeGenerator()


@pytest.fixture()
def ale():
    """Minimal AutonomousLearningEngine for topic inspection."""
    from modules.autonomous_learning_engine import AutonomousLearningEngine
    core = MagicMock()
    core.db = MagicMock()
    core.db.list_facts.return_value = []
    engine = AutonomousLearningEngine(
        core=core,
        idle_threshold=0,
        poll_interval=9999,
    )
    yield engine
    engine.running = False
    engine._stop_event.set()


# ─────────────────────────────────────────────────────────────────────────────
# CodeCompiler.syntax_test
# ─────────────────────────────────────────────────────────────────────────────

class TestSyntaxTestPython:
    def test_valid_python_is_valid(self, compiler):
        result = compiler.syntax_test("python", "def foo():\n    return 1\n")
        assert result["valid"] is True
        assert result["error"] is None

    def test_invalid_python_is_invalid(self, compiler):
        result = compiler.syntax_test("python", "def broken syntax !!")
        assert result["valid"] is False
        assert result["error"] is not None

    def test_empty_python_is_valid(self, compiler):
        result = compiler.syntax_test("python", "")
        assert result["valid"] is True

    def test_language_key_present(self, compiler):
        result = compiler.syntax_test("python", "x = 1")
        assert result["language"] == "python"


class TestSyntaxTestBash:
    def test_valid_bash_is_valid(self, compiler):
        code = "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"
        result = compiler.syntax_test("bash", code)
        assert result["valid"] is True

    def test_invalid_bash_is_invalid(self, compiler):
        # Unclosed if-then block
        result = compiler.syntax_test("bash", "if true\n  echo yes\n")
        assert result["valid"] is False

    def test_bash_language_normalised(self, compiler):
        code = "#!/usr/bin/env bash\necho hi\n"
        result = compiler.syntax_test("BASH", code)
        assert result["language"] == "bash"


class TestSyntaxTestUnknownLanguage:
    def test_unknown_language_passes_through(self, compiler):
        result = compiler.syntax_test("cobol", "IDENTIFICATION DIVISION.")
        # We cannot check unknown languages — should not raise
        assert isinstance(result["valid"], bool)


# ─────────────────────────────────────────────────────────────────────────────
# CodeCompiler.run — syntax pre-gate
# ─────────────────────────────────────────────────────────────────────────────

class TestRunSyntaxGate:
    def test_run_rejects_bad_python(self, compiler):
        result = compiler.run("python", "def broken !!")
        assert result.success is False
        assert "SyntaxError" in (result.error or "")

    def test_run_rejects_bad_bash(self, compiler):
        result = compiler.run("bash", "if [[")
        assert result.success is False
        assert "SyntaxError" in (result.error or "")

    def test_run_accepts_valid_python(self, compiler):
        result = compiler.run("python", "print('ok')\n")
        assert result.success is True

    def test_run_accepts_valid_bash(self, compiler):
        code = "#!/usr/bin/env bash\nset -euo pipefail\necho ok\n"
        result = compiler.run("bash", code)
        assert result.success is True


# ─────────────────────────────────────────────────────────────────────────────
# CodeCompiler.validate_syntax  (backwards-compat wrapper)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateSyntaxBackwardsCompat:
    def test_returns_dict(self, compiler):
        r = compiler.validate_syntax("python", "x = 1")
        assert isinstance(r, dict)

    def test_valid_python(self, compiler):
        r = compiler.validate_syntax("python", "x = 1")
        assert r["valid"] is True

    def test_invalid_python(self, compiler):
        r = compiler.validate_syntax("python", "x = !")
        assert r["valid"] is False


# ─────────────────────────────────────────────────────────────────────────────
# CodeGenerator.validate_structure
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateStructurePython:
    def test_valid_python_module(self, generator):
        code = "def foo():\n    pass\n"
        r = generator.validate_structure("python", code)
        assert r["valid"] is True
        assert r["issues"] == []

    def test_tab_indented_python_has_issue(self, generator):
        code = "def foo():\n\tpass\n"
        r = generator.validate_structure("python", code)
        assert r["valid"] is False
        assert any("tab" in issue.lower() or "Tab" in issue for issue in r["issues"])

    def test_returns_language_key(self, generator):
        r = generator.validate_structure("python", "x = 1")
        assert r["language"] == "python"


class TestValidateStructureBash:
    def test_missing_shebang_is_invalid(self, generator):
        r = generator.validate_structure("bash", "echo hello\n")
        assert r["valid"] is False
        assert any("shebang" in issue.lower() or "missing" in issue.lower() for issue in r["issues"])

    def test_missing_set_flags_is_invalid(self, generator):
        r = generator.validate_structure("bash", "#!/usr/bin/env bash\necho hello\n")
        assert r["valid"] is False
        assert any("set" in issue.lower() for issue in r["issues"])

    def test_well_structured_bash_is_valid(self, generator):
        code = "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"
        r = generator.validate_structure("bash", code)
        assert r["valid"] is True


class TestValidateStructureJavaScript:
    def test_missing_use_strict_is_invalid(self, generator):
        r = generator.validate_structure("javascript", "const x = 1;\n")
        assert r["valid"] is False

    def test_use_strict_present_is_valid(self, generator):
        r = generator.validate_structure("javascript", "'use strict';\nconst x = 1;\n")
        assert r["valid"] is True

    def test_var_declaration_flagged(self, generator):
        r = generator.validate_structure("javascript", "'use strict';\nvar x = 1;\n")
        assert r["valid"] is False


# ─────────────────────────────────────────────────────────────────────────────
# CodeGenerator.ensure_structure
# ─────────────────────────────────────────────────────────────────────────────

class TestEnsureStructure:
    def test_bash_gets_shebang_added(self, generator):
        code = "echo hello\n"
        fixed = generator.ensure_structure("bash", code)
        assert fixed.startswith("#!/usr/bin/env bash")

    def test_bash_gets_set_flags_added(self, generator):
        code = "#!/usr/bin/env bash\necho hello\n"
        fixed = generator.ensure_structure("bash", code)
        assert "set -euo pipefail" in fixed

    def test_bash_idempotent(self, generator):
        code = "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"
        fixed = generator.ensure_structure("bash", code)
        assert fixed.count("#!/usr/bin/env bash") == 1
        assert fixed.count("set -euo pipefail") == 1

    def test_python_tabs_converted(self, generator):
        code = "def foo():\n\tpass\n"
        fixed = generator.ensure_structure("python", code)
        assert "\t" not in fixed
        assert "    pass" in fixed

    def test_javascript_gets_use_strict(self, generator):
        code = "const x = 1;\n"
        fixed = generator.ensure_structure("javascript", code)
        assert "'use strict'" in fixed

    def test_javascript_idempotent(self, generator):
        code = "'use strict';\nconst x = 1;\n"
        fixed = generator.ensure_structure("javascript", code)
        assert fixed.count("'use strict'") == 1


# ─────────────────────────────────────────────────────────────────────────────
# CodeGenerator.generate_with_validation
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateWithValidation:
    def test_returns_success_for_python_module(self, generator):
        r = generator.generate_with_validation("python", "module", name="test_mod")
        assert r["success"] is True

    def test_structure_valid_for_python_module(self, generator):
        r = generator.generate_with_validation("python", "module", name="test_mod")
        assert r["structure_valid"] is True
        assert r["structure_issues"] == []

    def test_structure_issues_key_present(self, generator):
        r = generator.generate_with_validation("python", "module", name="test_mod")
        assert "structure_issues" in r

    def test_unsupported_language_returns_failure(self, generator):
        r = generator.generate_with_validation("cobol", "module", name="test_mod")
        assert r["success"] is False

    def test_bash_script_is_valid(self, generator):
        r = generator.generate_with_validation("bash", "script", name="my_script", body="echo hi")
        assert r["success"] is True
        assert r["structure_valid"] is True


# ─────────────────────────────────────────────────────────────────────────────
# New language templates in CodeGenerator
# ─────────────────────────────────────────────────────────────────────────────

class TestNewLanguageTemplates:
    """Ensure every newly added language/template can be generated without error."""

    @pytest.mark.parametrize("lang,tpl", [
        ("java",         "class"),
        ("c",            "program"),
        ("c",            "header"),
        ("cpp",          "class"),
        ("csharp",       "class"),
        ("rust",         "program"),
        ("rust",         "lib"),
        ("go",           "program"),
        ("go",           "package"),
        ("kotlin",       "class"),
        ("typescript",   "module"),
        ("swift",        "class"),
        ("ruby",         "class"),
        ("php",          "class"),
        ("assembly",     "x86_64"),
        ("assembly",     "arm"),
        ("makefile",     "c_project"),
        ("cmake",        "project"),
        ("networking",   "tcp_server_python"),
        ("networking",   "tcp_client_python"),
        ("networking",   "bash_network"),
        ("linux_kernel", "module"),
        ("linux_kernel", "char_device"),
        ("firmware",     "embedded_c"),
        ("firmware",     "bios_stub"),
        ("android",      "activity_java"),
        ("android",      "activity_kotlin"),
        ("android",      "manifest"),
        ("binary",       "reader"),
    ])
    def test_generates_successfully(self, generator, lang, tpl):
        r = generator.generate(lang, tpl, name="test_niblit", classname="TestNiblit",
                               docstring="Test.")
        assert r["success"] is True, f"{lang}/{tpl} failed: {r.get('error')}"
        assert len(r["code"]) > 0

    def test_supported_languages_includes_java(self, generator):
        from modules.code_generator import SUPPORTED_LANGUAGES
        assert "java" in SUPPORTED_LANGUAGES

    def test_supported_languages_includes_rust(self, generator):
        from modules.code_generator import SUPPORTED_LANGUAGES
        assert "rust" in SUPPORTED_LANGUAGES

    def test_supported_languages_includes_linux_kernel(self, generator):
        from modules.code_generator import SUPPORTED_LANGUAGES
        assert "linux_kernel" in SUPPORTED_LANGUAGES

    def test_supported_languages_includes_firmware(self, generator):
        from modules.code_generator import SUPPORTED_LANGUAGES
        assert "firmware" in SUPPORTED_LANGUAGES

    def test_extension_for_java(self, generator):
        assert generator.get_extension("java") == ".java"

    def test_extension_for_rust(self, generator):
        assert generator.get_extension("rust") == ".rs"


# ─────────────────────────────────────────────────────────────────────────────
# CodeGenerator.study_language (new languages)
# ─────────────────────────────────────────────────────────────────────────────

class TestStudyLanguageExpanded:
    @pytest.mark.parametrize("lang", [
        "java", "c", "cpp", "rust", "go", "kotlin", "typescript",
        "swift", "ruby", "php", "assembly",
    ])
    def test_returns_best_practices_header(self, generator, lang):
        result = generator.study_language(lang)
        assert "Best Practices" in result, f"Missing header for {lang}"

    def test_unknown_language_returns_fallback(self, generator):
        result = generator.study_language("cobol")
        assert "No study material" in result


# ─────────────────────────────────────────────────────────────────────────────
# CodeGenerator.study_domain
# ─────────────────────────────────────────────────────────────────────────────

class TestStudyDomain:
    @pytest.mark.parametrize("domain", [
        "networking", "operating_systems", "binary", "kernel",
        "firmware", "bios", "android", "linux", "security", "embedded",
    ])
    def test_returns_study_notes_header(self, generator, domain):
        result = generator.study_domain(domain)
        assert "Study Notes" in result, f"Missing header for domain '{domain}'"

    def test_networking_mentions_tcp(self, generator):
        result = generator.study_domain("networking")
        assert "TCP" in result or "socket" in result.lower()

    def test_binary_mentions_elf(self, generator):
        result = generator.study_domain("binary")
        assert "ELF" in result

    def test_kernel_mentions_module(self, generator):
        result = generator.study_domain("kernel")
        assert "module" in result.lower()

    def test_android_mentions_dex(self, generator):
        result = generator.study_domain("android")
        assert "DEX" in result or "dex" in result.lower()

    def test_unknown_domain_returns_fallback(self, generator):
        result = generator.study_domain("underwater_basket_weaving")
        assert "No domain notes" in result


# ─────────────────────────────────────────────────────────────────────────────
# BinaryTools module
# ─────────────────────────────────────────────────────────────────────────────

class TestBinaryToolsConversions:
    def setup_method(self):
        from modules.binary_tools import (
            to_hex, from_hex, to_binary_string, from_binary_string,
            int_to_representations, string_to_hex, string_to_binary, code_to_hex,
        )
        self.to_hex = to_hex
        self.from_hex = from_hex
        self.to_bin = to_binary_string
        self.from_bin = from_binary_string
        self.int_reps = int_to_representations
        self.str_hex = string_to_hex
        self.str_bin = string_to_binary
        self.code_hex = code_to_hex

    def test_hex_round_trip(self):
        data = b"Niblit!"
        assert self.from_hex(self.to_hex(data)) == data

    def test_binary_string_round_trip(self):
        data = b"\x41\x5a"
        assert self.from_bin(self.to_bin(data)) == data

    def test_int_representations_255(self):
        r = self.int_reps(255)
        assert r["hex"] == "0xff"
        assert r["binary"] == "0b11111111"
        assert r["octal"] == "0o377"
        assert r["decimal"] == "255"

    def test_int_representations_zero(self):
        r = self.int_reps(0)
        assert r["decimal"] == "0"

    def test_string_to_hex_is_reversible(self):
        text = "hello"
        assert bytes.fromhex(self.str_hex(text)).decode() == text

    def test_code_to_hex_has_required_keys(self):
        r = self.code_hex("print('hi')")
        assert "hex" in r
        assert "binary" in r
        assert "length_bytes" in r
        assert int(r["length_bytes"]) > 0

    def test_hex_strips_spaces(self):
        assert self.from_hex("41 42") == b"AB"


class TestBinaryToolsHexdump:
    def test_hexdump_contains_offset(self):
        from modules.binary_tools import hexdump
        result = hexdump(b"ABCDEFGHIJKLMNOP")
        assert "00000000" in result

    def test_hexdump_ascii_column(self):
        from modules.binary_tools import hexdump
        result = hexdump(b"Hello")
        assert "Hello" in result

    def test_hexdump_non_printable_shown_as_dot(self):
        from modules.binary_tools import hexdump
        result = hexdump(b"\x00\x01\x02")
        assert "..." in result


class TestBinaryStudier:
    def setup_method(self):
        from modules.binary_tools import BinaryStudier
        self.studier = BinaryStudier()

    def test_study_topic_elf_returns_note(self):
        result = self.studier.study_topic("elf")
        assert "ELF" in result

    def test_study_topic_hex_returns_note(self):
        result = self.studier.study_topic("hex")
        assert "hexadecimal" in result.lower() or "hex" in result.lower()

    def test_study_topic_unknown_returns_fallback(self):
        result = self.studier.study_topic("frobnicator")
        assert "[No offline note" in result

    def test_get_stats_has_topics_available(self):
        stats = self.studier.get_stats()
        assert "topics_available" in stats
        assert stats["topics_available"] > 0

    def test_seed_topics_without_db_returns_zero(self):
        count = self.studier.seed_topics()
        assert count == 0

    def test_get_topic_list_is_nonempty(self):
        topics = self.studier.get_topic_list()
        assert isinstance(topics, list)
        assert len(topics) > 0

    def test_analyze_nonexistent_file_returns_error(self):
        result = self.studier.analyze_file("/tmp/niblit_nonexistent_xyz.bin")
        assert "error" in result


class TestELFParsing:
    def test_non_elf_returns_error(self):
        from modules.binary_tools import parse_elf_header
        result = parse_elf_header(b"This is not ELF data")
        assert result.get("error") is not None

    def test_too_small_returns_error(self):
        from modules.binary_tools import parse_elf_header
        result = parse_elf_header(b"\x7fELF")
        assert "error" in result


class TestDEXParsing:
    def test_non_dex_returns_error(self):
        from modules.binary_tools import parse_dex_header
        result = parse_dex_header(b"This is not DEX data" + b"\x00" * 92)
        assert result.get("error") is not None


class TestAPKInspection:
    def test_nonexistent_apk_returns_error(self):
        from modules.binary_tools import inspect_apk
        result = inspect_apk("/tmp/niblit_nonexistent.apk")
        assert result["valid"] is False
        assert result["error"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# ALE expanded topics
# ─────────────────────────────────────────────────────────────────────────────

class TestALEExpandedTopics:
    def test_research_topics_include_binary(self, ale):
        joined = " ".join(ale.research_topics)
        assert "binary" in joined.lower() or "hex" in joined.lower()

    def test_research_topics_include_networking(self, ale):
        joined = " ".join(ale.research_topics)
        assert "networking" in joined.lower() or "network" in joined.lower()

    def test_research_topics_include_kernel(self, ale):
        joined = " ".join(ale.research_topics)
        assert "kernel" in joined.lower()

    def test_research_topics_include_firmware(self, ale):
        joined = " ".join(ale.research_topics)
        assert "firmware" in joined.lower()

    def test_code_research_includes_java(self, ale):
        langs = [lang for lang, _ in ale.code_research_topics]
        assert "java" in langs

    def test_code_research_includes_rust(self, ale):
        langs = [lang for lang, _ in ale.code_research_topics]
        assert "rust" in langs

    def test_code_research_includes_c(self, ale):
        langs = [lang for lang, _ in ale.code_research_topics]
        assert "c" in langs

    def test_software_study_categories_include_binary_analysis(self, ale):
        assert "binary_analysis" in ale.software_study_categories

    def test_software_study_categories_include_kernel(self, ale):
        assert "kernel_development" in ale.software_study_categories

    def test_software_study_categories_include_android(self, ale):
        assert "android_internals" in ale.software_study_categories


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
