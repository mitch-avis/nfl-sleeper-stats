"""Tests for project constants and path resolution."""

import json
from pathlib import Path

from nfl_sleeper_stats import constants


def test_resolve_project_root_prefers_repo_cwd_when_module_file_is_elsewhere(
    tmp_path: Path,
) -> None:
    """Resolve the project root from the current repo when module files live elsewhere."""
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "nfl_sleeper_stats"
    package_dir.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")

    site_packages_module = tmp_path / "site-packages" / "nfl_sleeper_stats" / "constants.py"
    site_packages_module.parent.mkdir(parents=True)
    site_packages_module.write_text("", encoding="utf-8")

    assert (
        constants.resolve_project_root(
            cwd=repo_root,
            module_file=site_packages_module,
        )
        == repo_root
    )


def test_used_stats_keeps_bonus_pass_cmp_column_name() -> None:
    """Keep the curated output column name aligned with the known Sleeper stat name."""
    assert "bonus_pass_cmp_25" in constants.USED_STATS["ALL"]


def test_all_stats_includes_saved_2025_snapshot_fields() -> None:
    """Keep the raw Sleeper stat catalog broad enough to cover the saved 2025 payload."""
    payload_path = Path(__file__).resolve().parent.parent / "2025_all_stats.json"
    with payload_path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    stat_fields = sorted({field for entry in payload.values() for field in entry})
    missing_fields = sorted(set(stat_fields) - set(constants.ALL_STATS))

    assert missing_fields == []
