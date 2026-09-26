"""Tests for multi-device path resolution and sync merge preservation."""
import tempfile
from pathlib import Path

from agents_memory.remote.merge import merge_table_markdown_with_conflicts
from agents_memory.remote.sync_bundle import _SKIP_NAMES
from agents_memory.store import Project, load_host_paths, save_host_path


def test_host_paths_json_skipped_in_sync():
    """Ensure host_paths.json is never collected or synced to the cloud bundle."""
    assert "host_paths.json" in _SKIP_NAMES


def test_project_path_obj_dynamic_resolution(monkeypatch, tmp_path):
    """When self.path is from another OS, resolve dynamically via scan roots."""
    roots_dir = tmp_path / "Coding"
    roots_dir.mkdir(parents=True)
    repo_dir = roots_dir / "veadio"
    repo_dir.mkdir()

    monkeypatch.setattr("agents_memory.store.scan_roots", lambda: [str(roots_dir)])
    monkeypatch.setattr("agents_memory.store.load_host_paths", lambda: {})

    # Foreign Windows/Unix path (non-existent on current host)
    p = Project(slug="veadio", path=r"Z:\foreign_device\Coding\veadio", role="app", stack="TS")
    assert p.path_obj == repo_dir
    assert p.path_obj.is_dir()


def test_project_path_obj_host_override(monkeypatch, tmp_path):
    """Host-local override in host_paths.json takes precedence."""
    custom_dir = tmp_path / "custom" / "my-veadio"
    custom_dir.mkdir(parents=True)

    monkeypatch.setattr("agents_memory.store.load_host_paths", lambda: {"veadio": str(custom_dir)})

    p = Project(slug="veadio", path=r"Z:\foreign_device\Coding\veadio", role="app", stack="TS")
    assert p.path_obj == custom_dir


def test_merge_projects_table_preserves_local_path(tmp_path):
    """When incoming has a foreign non-existent path, keep the working local path."""
    local_repo = tmp_path / "veadio"
    local_repo.mkdir()

    base_table = (
        "| slug | path | role | stack | status |\n"
        "|------|------|------|-------|--------|\n"
        f"| veadio | `{local_repo}` | Reader | TS | active |\n"
    )

    incoming_table = (
        "| slug | path | role | stack | status |\n"
        "|------|------|------|-------|--------|\n"
        r"| veadio | `Z:\foreign_device\Coding\veadio` | Reader | TS | active |" "\n"
    )

    merged, conflicts = merge_table_markdown_with_conflicts(base_table, incoming_table)
    assert f"`{local_repo}`" in merged
    assert "foreign_device" not in merged
    # Pure path difference should not log conflict
    assert len(conflicts) == 0


def test_merge_projects_table_updates_metadata_while_keeping_local_path(tmp_path):
    """Update role/stack from incoming even while retaining local working path."""
    local_repo = tmp_path / "veadio"
    local_repo.mkdir()

    base_table = (
        "| slug | path | role | stack | status |\n"
        "|------|------|------|-------|--------|\n"
        f"| veadio | `{local_repo}` | MVP | TS | active |\n"
    )

    incoming_table = (
        "| slug | path | role | stack | status |\n"
        "|------|------|------|-------|--------|\n"
        r"| veadio | `Z:\foreign_device\Coding\veadio` | Production App | TS, Python | active |" "\n"
    )

    merged, conflicts = merge_table_markdown_with_conflicts(base_table, incoming_table)
    assert f"`{local_repo}`" in merged
    assert "Production App" in merged
    assert "TS, Python" in merged
    # Metadata difference was merged, conflict logged for audit
    assert len(conflicts) == 1
    assert conflicts[0]["slug"] == "veadio"
