from modules.agent_capability_index import (
    extract_windows_paths,
    filter_by_provider_scope,
    rank_capabilities,
    retrieve_capabilities,
)


def _schema(name, description, properties=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": [],
                "additionalProperties": False,
            },
        },
    }


def test_extract_windows_absolute_paths():
    assert extract_windows_paths(r"Inspect D:\models and C:\repo\README.md.") == [
        r"D:\models", r"C:\repo\README.md"
    ]


def test_bm25_ranks_directory_listing_for_file_inventory():
    schemas = {
        "mcp_desktop_commander_list_directory": _schema(
            "list_directory", "List all files and directories at an absolute host path.",
            {"path": {"type": "string", "description": "Absolute directory path"}},
        ),
        "mcp_desktop_commander_read_file": _schema(
            "read_file", "Read the contents of one file at a host path.",
            {"path": {"type": "string", "description": "Absolute file path"}},
        ),
        "mcp_git_status": _schema("git_status", "Inspect repository status and changed files."),
    }
    ranked = rank_capabilities(
        r"list the files and folders in D:\models",
        [{"name": name, "schema": schema, "metadata": {"provider": "desktop_commander"}}
         for name, schema in schemas.items()],
        top_k=3,
    )
    assert ranked[0] == "mcp_desktop_commander_list_directory"


def test_external_drive_path_excludes_workspace_scoped_filesystem_provider():
    schemas = {
        "mcp_filesystem_list_directory": _schema(
            "list_directory", "List directory contents inside the configured workspace.",
            {"path": {"type": "string", "description": "Workspace-relative path"}},
        ),
        "mcp_desktop_commander_list_directory": _schema(
            "list_directory", "List directory contents on the host desktop.",
            {"path": {"type": "string", "description": "Absolute host path"}},
        ),
    }
    metadata = {
        "mcp_filesystem_list_directory": {
            "provider": "filesystem",
            "scope": "workspace_filesystem",
            "allowed_roots": [r"C:\repo"],
        },
        "mcp_desktop_commander_list_directory": {
            "provider": "desktop_commander",
            "scope": "host_filesystem",
            "allowed_roots": [],
        },
    }
    names = retrieve_capabilities(r"Inspect D:\models", schemas, metadata, top_k=12)
    assert names == ["mcp_desktop_commander_list_directory"]


def test_workspace_provider_remains_eligible_for_paths_inside_its_root():
    records = [
        {"name": "filesystem", "schema": _schema("list_directory", "List workspace directories."),
         "metadata": {"provider": "filesystem", "scope": "workspace_filesystem",
                      "allowed_roots": [r"C:\repo"]}},
        {"name": "desktop", "schema": _schema("list_directory", "List host directories."),
         "metadata": {"provider": "desktop_commander", "scope": "host_filesystem"}},
    ]
    eligible = filter_by_provider_scope(r"Inspect C:\repo\docs", records)
    assert {item["name"] for item in eligible} == {"filesystem", "desktop"}


def test_explicit_desktop_commander_provider_request_is_respected():
    schemas = {
        "mcp_filesystem_read_text_file": _schema("read_text_file", "Read workspace files."),
        "mcp_desktop_commander_read_file": _schema("read_file", "Read host files."),
    }
    metadata = {
        "mcp_filesystem_read_text_file": {"provider": "filesystem", "scope": "workspace_filesystem",
                                          "allowed_roots": [r"C:\repo"]},
        "mcp_desktop_commander_read_file": {"provider": "desktop_commander", "scope": "host_filesystem"},
    }
    names = retrieve_capabilities(
        r"Use Desktop Commander to read C:\repo\README.md",
        schemas, metadata, top_k=12,
    )
    assert names == ["mcp_desktop_commander_read_file"]


def test_capability_retrieval_never_expands_callers_allow_list():
    schemas = {
        "mcp_desktop_commander_list_directory": _schema("list_directory", "List host directories."),
    }
    names = retrieve_capabilities("inspect files", schemas, {}, top_k=20)
    assert names == ["mcp_desktop_commander_list_directory"]
