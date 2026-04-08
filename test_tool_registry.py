"""
test_tool_registry.py — Unit tests for niblit_tools/tool_registry.py

Covers:
  - ToolRegistry: register, list_tools, get_schema, run, __contains__
  - @tool decorator (with and without arguments)
  - Module-level singleton via get_registry()
  - Built-in niblit_serpex_search registration

Run with::

    pytest test_tool_registry.py -v
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_registry():
    """Return a new ToolRegistry with no pre-registered tools."""
    from niblit_tools.tool_registry import ToolRegistry
    return ToolRegistry()


# ---------------------------------------------------------------------------
# ToolRegistry.register / list_tools / get_schema / __contains__
# ---------------------------------------------------------------------------

class TestToolRegistryRegister:
    def test_register_adds_function(self):
        reg = _fresh_registry()

        def add(a: int, b: int) -> int:
            return a + b

        reg.register(add, description="Add two numbers")
        assert "add" in reg

    def test_register_stores_definition(self):
        reg = _fresh_registry()

        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}"

        reg.register(greet)
        defn = reg.get_schema("greet")
        assert defn is not None
        assert defn["name"] == "greet"
        assert "parameters" in defn

    def test_register_custom_name(self):
        reg = _fresh_registry()

        def _internal(x: str) -> str:
            return x

        reg.register(_internal, name="my_tool", description="desc")
        assert "my_tool" in reg
        assert "_internal" not in reg

    def test_register_uses_docstring_as_description(self):
        reg = _fresh_registry()

        def fn() -> None:
            """This is the docstring."""
            pass

        reg.register(fn)
        assert reg.get_schema("fn")["description"] == "This is the docstring."

    def test_register_explicit_description_overrides_docstring(self):
        reg = _fresh_registry()

        def fn() -> None:
            """Docstring."""
            pass

        reg.register(fn, description="Explicit description")
        assert reg.get_schema("fn")["description"] == "Explicit description"


class TestToolRegistryListTools:
    def test_list_tools_empty(self):
        reg = _fresh_registry()
        assert reg.list_tools() == []

    def test_list_tools_returns_all_registered(self):
        reg = _fresh_registry()

        def a() -> None: pass
        def b() -> None: pass

        reg.register(a)
        reg.register(b)
        names = [t["name"] for t in reg.list_tools()]
        assert "a" in names
        assert "b" in names

    def test_list_tools_returns_copies(self):
        reg = _fresh_registry()

        def fn() -> None: pass
        reg.register(fn)

        tools = reg.list_tools()
        tools.clear()
        # Original registry should still have the tool
        assert reg.list_tools() != []


class TestToolRegistryGetSchema:
    def test_get_schema_unknown_returns_none(self):
        reg = _fresh_registry()
        assert reg.get_schema("nonexistent") is None

    def test_get_schema_has_required_keys(self):
        reg = _fresh_registry()

        def fn(x: int) -> int:
            return x

        reg.register(fn)
        schema = reg.get_schema("fn")
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema

    def test_get_schema_parameters_structure(self):
        reg = _fresh_registry()

        def multiply(a: int, b: int) -> int:
            return a * b

        reg.register(multiply)
        params = reg.get_schema("multiply")["parameters"]
        assert params["type"] == "object"
        assert "a" in params["properties"]
        assert "b" in params["properties"]
        assert "a" in params["required"]
        assert "b" in params["required"]

    def test_optional_param_not_required(self):
        reg = _fresh_registry()

        def search(query: str, max_results: int = 10) -> list:
            return []

        reg.register(search)
        params = reg.get_schema("search")["parameters"]
        assert "query" in params["required"]
        assert "max_results" not in params["required"]


# ---------------------------------------------------------------------------
# ToolRegistry.run
# ---------------------------------------------------------------------------

class TestToolRegistryRun:
    def test_run_calls_function(self):
        reg = _fresh_registry()
        called_with = {}

        def my_tool(x: int, y: int) -> int:
            called_with["x"] = x
            called_with["y"] = y
            return x + y

        reg.register(my_tool)
        result = reg.run("my_tool", {"x": 3, "y": 4})
        assert result == 7
        assert called_with == {"x": 3, "y": 4}

    def test_run_unknown_tool_raises_key_error(self):
        reg = _fresh_registry()
        with pytest.raises(KeyError, match="Unknown tool"):
            reg.run("does_not_exist", {})

    def test_run_none_arguments_treated_as_empty(self):
        reg = _fresh_registry()

        def no_args() -> str:
            return "ok"

        reg.register(no_args)
        assert reg.run("no_args", None) == "ok"

    def test_run_wrong_args_raises_type_error(self):
        reg = _fresh_registry()

        def strict(x: int) -> int:
            return x

        reg.register(strict)
        with pytest.raises(TypeError):
            reg.run("strict", {"wrong_param": 1})


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

class TestToolDecorator:
    def setup_method(self):
        # Reset the module-level singleton before each test
        import niblit_tools.tool_registry as _tr
        _tr._registry = None

    def test_decorator_without_args(self):
        from niblit_tools.tool_registry import tool, get_registry

        @tool
        def decorated_fn(x: str) -> str:
            return x

        assert "decorated_fn" in get_registry()

    def test_decorator_with_description(self):
        from niblit_tools.tool_registry import tool, get_registry

        @tool(description="A test tool")
        def described_fn(q: str) -> str:
            return q

        schema = get_registry().get_schema("described_fn")
        assert schema["description"] == "A test tool"

    def test_decorator_with_name_override(self):
        from niblit_tools.tool_registry import tool, get_registry

        @tool(name="renamed_tool")
        def original_name(x: int) -> int:
            return x

        assert "renamed_tool" in get_registry()
        assert "original_name" not in get_registry()

    def test_decorator_returns_original_function(self):
        from niblit_tools.tool_registry import tool

        @tool
        def passthrough(x: int) -> int:
            return x * 2

        assert passthrough(5) == 10

    def test_decorator_with_args_returns_original_function(self):
        from niblit_tools.tool_registry import tool

        @tool(description="desc")
        def passthrough2(x: int) -> int:
            return x * 3

        assert passthrough2(4) == 12


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

class TestGetRegistry:
    def setup_method(self):
        import niblit_tools.tool_registry as _tr
        _tr._registry = None

    def test_get_registry_returns_same_instance(self):
        from niblit_tools.tool_registry import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_get_registry_is_tool_registry_instance(self):
        from niblit_tools.tool_registry import get_registry, ToolRegistry
        assert isinstance(get_registry(), ToolRegistry)

    def test_builtin_serpex_tool_registered(self):
        """niblit_serpex_search should be pre-registered in the default registry."""
        # Patch the import so no real ScrapySearchEngine is needed
        mock_fn = MagicMock(return_value=[])
        mock_def = {
            "name": "niblit_serpex_search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
        with patch.dict(
            "sys.modules",
            {
                "niblit_tools.serpex_api": MagicMock(
                    niblit_serpex_search=mock_fn,
                    NIBLIT_SERPEX_TOOL=mock_def,
                )
            },
        ):
            import niblit_tools.tool_registry as _tr
            _tr._registry = None  # force re-init with patched imports
            from niblit_tools.tool_registry import get_registry
            reg = get_registry()
            # The tool should have been registered
            assert "niblit_serpex_search" in reg


# ---------------------------------------------------------------------------
# Public __init__.py re-exports
# ---------------------------------------------------------------------------

class TestPackageExports:
    def test_tool_exported(self):
        import niblit_tools
        assert hasattr(niblit_tools, "tool")

    def test_get_registry_exported(self):
        import niblit_tools
        assert hasattr(niblit_tools, "get_registry")

    def test_tool_registry_class_exported(self):
        import niblit_tools
        assert hasattr(niblit_tools, "ToolRegistry")

    def test_serpex_exports_still_present(self):
        import niblit_tools
        assert hasattr(niblit_tools, "SerpexAPI")
        assert hasattr(niblit_tools, "niblit_serpex_search")
        assert hasattr(niblit_tools, "NIBLIT_SERPEX_TOOL")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
