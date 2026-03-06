"""Tests for flow._storage."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from flow._models import FlowConfig
from flow._storage import (
    add_project,
    load_config,
    load_projects,
    save_config,
    save_projects,
    set_active_project,
)


@pytest.fixture
def mock_storage(tmp_path: Path):
    """Patch storage paths to use a temp directory."""
    storage_root = tmp_path / ".flow-py"
    profile_dir = storage_root / "browser-profile"
    config_file = storage_root / "config.json"
    projects_file = storage_root / "projects.json"

    with patch("flow._storage.STORAGE_ROOT", storage_root), \
         patch("flow._storage.PROFILE_DIR", profile_dir), \
         patch("flow._storage.CONFIG_FILE", config_file), \
         patch("flow._storage.PROJECTS_FILE", projects_file):
        yield tmp_path


def test_load_save_config(mock_storage):
    """Config round-trips through save/load."""
    cfg = FlowConfig(headless=False, default_output_dir="/tmp/out")
    save_config(cfg)

    loaded = load_config()
    assert loaded.headless is False
    assert loaded.default_output_dir == "/tmp/out"
    assert loaded.generation_timeout_s == 300  # default preserved


def test_load_config_missing(mock_storage):
    """Loading when no config file exists returns defaults."""
    cfg = load_config()
    assert cfg.headless is True
    assert cfg.default_output_dir == "."


def test_add_project(mock_storage):
    """Projects can be added and retrieved."""
    add_project("abc123", "My Project", "https://labs.google/fx/tools/flow/project/abc123")
    add_project("def456", "Another", "https://labs.google/fx/tools/flow/project/def456")

    projects = load_projects()
    assert len(projects) == 2
    assert projects["abc123"]["name"] == "My Project"
    assert projects["def456"]["url"] == "https://labs.google/fx/tools/flow/project/def456"


def test_set_active_project(mock_storage):
    """Setting active project updates the config."""
    set_active_project("abc123", "https://labs.google/fx/tools/flow/project/abc123")

    cfg = load_config()
    assert cfg.active_project_id == "abc123"
    assert cfg.active_project_url == "https://labs.google/fx/tools/flow/project/abc123"

    # Clear active project
    set_active_project(None)
    cfg = load_config()
    assert cfg.active_project_id is None
