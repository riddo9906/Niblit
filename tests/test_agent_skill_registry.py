from pathlib import Path
from tempfile import TemporaryDirectory

from modules.agent_skill_registry import SkillRegistry


def test_builtin_skill_packs_are_discovered_and_loadable():
    root = Path(__file__).resolve().parents[1] / "skills"
    registry = SkillRegistry(roots=[root])
    catalog = registry.list_skills()
    names = {item["name"] for item in catalog["skills"]}
    assert catalog["count"] == 8
    assert "software-engineering" in names
    loaded = registry.load_skill("software-engineering")
    assert "Preserve all existing user changes" in loaded["content"]
    assert loaded["source"] == "built-in"


def test_user_skill_search_and_loading_are_markdown_only():
    with TemporaryDirectory(prefix=".skill-registry-test-", dir=str(Path(__file__).resolve().parents[1])) as folder:
        root = Path(folder)
        skill_dir = root / "docker-workflows"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: docker-workflows\ndescription: Manage Docker Compose and containers safely.\n---\n# Docker workflows\nAsk for approval before mutations.\n",
            encoding="utf-8",
        )
        (skill_dir / "run.ps1").write_text("Write-Host 'not loaded'", encoding="utf-8")
        registry = SkillRegistry(roots=[root])
        matches = registry.search_skills("docker compose")
        assert matches["skills"][0]["name"] == "docker-workflows"
        loaded = registry.load_skill("docker-workflows")
        assert "Ask for approval" in loaded["content"]
        assert "run.ps1" not in loaded["content"]


def test_skill_registry_does_not_resolve_paths_from_model_input():
    registry = SkillRegistry(roots=[])
    assert registry.load_skill("..").get("error") == "skill_not_found"
