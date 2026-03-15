"""
test_code_tools.py — Unit tests for CodeCompiler.syntax_test and
CodeGenerator.validate_structure / ensure_structure / generate_with_validation.

Run with::

    pytest test_code_tools.py -v
"""

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
